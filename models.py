import datetime
import hashlib

from google.appengine.ext import ndb as db
from google.appengine.api import memcache
from google.appengine.api import users

PAGE_SIZE = 20
DAY_SCALE = 4

class Counter(db.Model):
  counter = db.IntegerProperty()

class Quote(db.Model):
  quote = db.StringProperty(required=True)
  uri   = db.StringProperty()
  rank = db.IntegerProperty(indexed=True)
  created = db.IntegerProperty(default=0)
  creation_order = db.StringProperty(default=" ")
  votesum = db.IntegerProperty(default=0)
  up_votes = db.IntegerProperty(default=0)
  down_votes = db.IntegerProperty(default=0)
  creator = db.UserProperty()
  q_type = db.BooleanProperty(default=False) # true if is comment
  topic = db.StringProperty(default="General")

class Vote(db.Model):
  vote = db.IntegerProperty(default=0)


class Voter(db.Model):
  count = db.IntegerProperty(default=0)
  hasVoted = db.BooleanProperty(default=False)
  hasAddedQuote = db.BooleanProperty(default=False)
  karma = db.IntegerProperty(default=1)


def _get_or_create_voter(user):
  """
  Find a matching Voter or create a new one with the
  email as the key_name.
  
  Returns a Voter for the given user.
  """
  voter = Voter.get_by_id(id=user.email())
  if voter is None:
    voter = Voter(id=user.email())
  return voter

def _get_or_create_counter(topic):
  counter = Counter.get_by_id(id=topic)
  if counter is None:
    counter = Counter(id=topic, counter=0)
  return counter

def get_progress(user):
  """
  Returns (hasVoted, hasAddedQuote) for the given user
  """
  voter = _get_or_create_voter(user)
  return voter.hasVoted, voter.hasAddedQuote
  

def _set_progress_hasVoted(user):
  """
  Sets Voter.hasVoted = True for the given user.
  """

  def txn():
    voter = _get_or_create_voter(user)
    if not voter.hasVoted:
      voter.hasVoted = True
      voter.put()
      
  db.transaction(txn)


def _unique_user(user, transact=True):
  """
  Creates a unique string by using an increasing
  counter sharded per user. The resulting string
  is hashed to keep the users email address private.
  """
  
  def txn():
    voter = _get_or_create_voter(user)
    voter.count += 1
    voter.hasAddedQuote = True
    voter.put()
    return voter.count

  if transact:
    count = db.transaction(txn)
  else:
    count = txn()

  return hashlib.md5(user.email() + "|" + str(count)).hexdigest()
  

def add_quote(text, user, uri=None, _created=None, topic=None):
  def txn():
    try:
      now = datetime.datetime.now()
      unique_user = _unique_user(user, transact=False)
      if _created:
        created = _created
      else:
        created = (now - datetime.datetime(2008, 10, 1)).days
      voter = _get_or_create_voter(user)
      voter.karma += 1

      q = Quote(
        quote=text,
        created=created,
        creator=user,
        creation_order=now.isoformat()[:19] + "|" + unique_user,
        uri=uri,
        q_type=False,
        topic=topic,
      )

      counter = None
      if topic not in ['General', '', None]:
        counter = _get_or_create_counter(topic)
        counter.counter += 1

      if counter:
        db.put_multi([q, voter, counter])
      else:
        db.put_multi([q, voter])

      return q.key
    except:
      return None
  return db.transaction(txn, xg=True)

def del_quote(quote_id, user):
  q = Quote.get_by_id(quote_id)
  if q is not None and (users.is_current_user_admin() or q.creator == user):
    q.delete()


def get_quote(quote_id):
  return db.Key(urlsafe=quote_id).get()


def get_quotes_newest(offset=None):
  extra = None
  if offset is None:
    quotes = Quote.query(Quote.q_type == False).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)
  else:
    quotes = Quote.query(db.AND(Quote.q_type == False, Quote.creation_order <= offset)).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)
    
  if len(quotes) > PAGE_SIZE:
    extra = quotes[-1].creation_order
    quotes = quotes[:PAGE_SIZE]
  return quotes, extra


def get_quotes_by_topic(offset=None, topic=None):
  extra = None
  if topic is None and offset is None:
    quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == None)).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)
  elif topic is None and offset is not None:
    quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == None, Quote.creation_order <= offset)).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)
  elif topic is not None and offset is None:
    quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == topic)).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)
  else:
    quotes = Quote.query(db.AND(Quote.q_type == False, topic == topic, Quote.creation_order <= offset)).order(-Quote.creation_order).fetch(PAGE_SIZE + 1)

  if len(quotes) > PAGE_SIZE:
    extra = quotes[-1].creation_order
    quotes = quotes[:PAGE_SIZE]
  return quotes, extra


def rank_quote(ups, downs, date):
  from datetime import datetime
  from math import log

  epoch = datetime(1970, 1, 1)

  def epoch_seconds(date):
      td = date - epoch
      return td.days * 86400 + td.seconds + (float(td.microseconds) / 1000000)

  def score(ups, downs):
      return ups - downs

  def hot(ups, downs, date):
      s = score(ups, downs)
      order = log(max(abs(s), 1), 10)
      sign = 1 if s > 0 else -1 if s < 0 else 0
      seconds = epoch_seconds(date) - 1134028003
      return round(sign * order + seconds / 45000, 7)

  return hot(ups, downs, date)

def set_vote(quote_id, user, newvote):
  if user is None:
    return
  
  def txn():
    voter = _get_or_create_voter(user)
    if voter.hasVoted:
      return

    quote = db.Key(urlsafe=quote_id).get()
    if quote is None:
      return
    if quote.creator != user:
      voter.karma += 1
    creator_voter = _get_or_create_voter(quote.creator)
    creator_voter.karma += newvote

    vote = Vote.get_by_id(id=user.email(), parent=quote.key)
    if vote is None:
      vote = Vote(id=user.email(), parent=quote.key)
    if vote.vote == newvote:
      return

    vote.vote = newvote

    quote.up_votes += 1 if vote.vote == 1 else 0
    quote.down_votes += 1 if vote.vote == -1 else 0

    # See the docstring of main.py for an explanation of
    # the following formula.
    # quote.rank = "%020d|%s" % (
    #   long(quote.created * DAY_SCALE + quote.votesum),
    #   quote.creation_order
    #   )
    quote.rank = rank_quote(quote.up_votes, quote.down_votes, datetime.datetime.now())
    db.put_multi([vote, quote, voter])
    memcache.set("vote|" + user.email() + "|" + str(quote_id), vote.vote)

  db.transaction(txn, xg=True)
  _set_progress_hasVoted(user)

  
def get_quotes(page=0, topic=None):
  assert page >= 0
  assert page < 20
  extra = None
  if topic is None or topic == '' or topic.lower() == 'general':
    quotes = Quote.query(db.OR(Quote.topic == None, Quote.topic == '', Quote.topic == 'General')).order(-Quote.rank).fetch(PAGE_SIZE+1)
  else:
    quotes = Quote.query(Quote.topic == topic).order(-Quote.rank).fetch(PAGE_SIZE+1)

  if len(quotes) > PAGE_SIZE:
    if page < 19:
      extra = quotes[-1]
    quotes = quotes[:PAGE_SIZE]
  return quotes, extra


def voted(quote, user):
  val = 0
  if user:
    memcachekey = "vote|" + user.email() + "|" + str(quote.key)
    val = memcache.get(memcachekey)
    if val is not None:
      return val
    vote = Vote.get_by_id(id=user.email(), parent=quote.key)
    if vote is not None:
      val = vote.vote
      memcache.set(memcachekey, val)
  return val

def get_comments_for_quote(quote_id):
  comments = Quote.query(ancestor=quote_id).filter(Quote.q_type == True)
  return comments

def comment_on_quote(quote, user, comment_text):
  def txn():
    now = datetime.datetime.now()
    unique_user = _unique_user(user, transact=False)
    voter = _get_or_create_voter(user)
    voter.karma += 1
    created = (now - datetime.datetime(2008, 10, 1)).days
    comment = Quote(
      quote=comment_text,
      created=created,
      creator=user,
      creation_order=now.isoformat()[:19] + "|" + unique_user,
      parent=quote.key,
      q_type=True,
    )
    return db.put_multi([comment, voter])
  return db.transaction(txn, xg=True)


def get_trending_topics():
  return [t.key.id() for t in Counter.query().order(-Counter.counter).fetch(10)]

