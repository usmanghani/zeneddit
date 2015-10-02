# Copyright 2008 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Model classes and utility functions for handling
Quotes, Votes and Voters in the Overheard application.

"""


import datetime
import hashlib

from google.appengine.ext import ndb as db
from google.appengine.api import memcache
from google.appengine.api import users

PAGE_SIZE = 20
DAY_SCALE = 4

class Quote(db.Model):
  """Storage for a single quote and its metadata
  
  Properties
    quote:          The quote as a string
    uri:            An optional URI that is the source of the quotation
    rank:           A calculated ranking based on the number of votes and when the quote was added.
    created:        When the quote was created, recorded in the number of days since the beginning of our local epoch.
    creation_order: Totally unique index on all quotes in order of their creation.
    creator:        The user that added this quote.
  """
  quote = db.StringProperty(required=True)
  uri   = db.StringProperty()
  rank = db.StringProperty(indexed=True)
  created = db.IntegerProperty(default=0)
  creation_order = db.StringProperty(default=" ", indexed=True)
  votesum = db.IntegerProperty(default=0)
  up_votes = db.IntegerProperty(default=0)
  down_votes = db.IntegerProperty(default=0)
  creator = db.UserProperty()
  q_type = db.BooleanProperty(default=False, indexed=True) # true if is comment
  topic = db.StringProperty(default="General", indexed=True)

# class Comment(db.Model):
#   text = db.StringProperty(required=True, multiline=True)
#   quote_id = db.IntegerProperty(required=True)
#   # parent_comment_id = db.IntegerProperty(required=False)
#   user = db.UserProperty(required=True)
#   created = db.IntegerProperty(required=True)

class Vote(db.Model):
  """Storage for a single vote by a single user on a single quote.
  

  Index
    key_name: The email address of the user that voted.
    parent:   The quote this is a vote for.
  
  Properties
    vote: The value of 1 for like, -1 for dislike.
  """
  vote = db.IntegerProperty(default=0)


class Voter(db.Model):
  """Storage for metadata about each user
  
  Properties
    count:          An integer that gets incremented with users addition of a quote. 
                      Used to build a unique index for quote creation.
    hasVoted:       Has this user ever voted on a quote.
    hasAddedQuote:  Has this user ever added a quote.
  """
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
  """
  Add a new quote to the datastore.
  
  Parameters
    text:     The text of the quote
    user:     User who is adding the quote
    uri:      Optional URI pointing to the origin of the quote.
    _created: Allows the caller to override the calculated created 
                value, used only for testing.
  
  Returns  
    The id of the quote or None if the add failed.
  """
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

      db.put_multi([q, voter])
      return q.key
    except:
      return None
  return db.transaction(txn, xg=True)

def del_quote(quote_id, user):
  """
  Remove a quote.
  
  User must be the creator of the quote or a site administrator.
  """
  q = Quote.get_by_id(quote_id)
  if q is not None and (users.is_current_user_admin() or q.creator == user):
    q.delete()


def get_quote(quote_id):
  """
  Retrieve a single quote.
  """
  return db.Key(urlsafe=quote_id).get()


def get_quotes_newest(offset=None):
  """
  Returns 10 quotes per page in created order.
  
  Args 
    offset:  The id to use to start the page at. This is the value of 'extra'
               returned from a previous call to this function.
    
  Returns
    (quotes, extra)
  """
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
  """
  Returns 10 quotes per page in created order.

  Args
    offset:  The id to use to start the page at. This is the value of 'extra'
               returned from a previous call to this function.

  Returns
    (quotes, extra)
  """
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


def set_vote(quote_id, user, newvote):
  """
  Record 'user' casting a 'vote' for a quote with an id of 'quote_id'.
  The 'newvote' is usually an integer in [-1, 0, 1].
  """
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
    quote.rank = "%020d|%s" % (
      long(quote.created * DAY_SCALE + quote.votesum), 
      quote.creation_order
      )
    db.put_multi([vote, quote, voter])
    memcache.set("vote|" + user.email() + "|" + str(quote_id), vote.vote)

  db.transaction(txn, xg=True)
  _set_progress_hasVoted(user)

  
def get_quotes(page=0, topic=None):
  """Returns PAGE_SIZE quotes per page in rank order. Limit to 20 pages."""
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
  """Returns the value of a users vote on the specified quote, a value in [-1, 0, 1]."""
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
