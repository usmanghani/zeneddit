import datetime
import hashlib
import secure

from google.appengine.ext import ndb as db
from google.appengine.api import memcache
from google.appengine.api import users

PAGE_SIZE = 20
DAY_SCALE = 4


class Counter(db.Model):
	counter = db.IntegerProperty()


class Quote(db.Model):
	quote = db.StringProperty(required=True)
	text = db.StringProperty()
	uri = db.StringProperty()
	rank = db.IntegerProperty(indexed=True)
	created = db.IntegerProperty(default=0)
	creation_order = db.StringProperty(default=" ")
	votesum = db.IntegerProperty(default=0)
	up_votes = db.IntegerProperty(default=0)
	down_votes = db.IntegerProperty(default=0)
	creator = db.KeyProperty(kind='User')
	q_type = db.BooleanProperty(default=False)  # true if is comment
	topic = db.StringProperty(default="General")


class User(db.Model):
	_use_memcache = True

	useremail = db.StringProperty(required=True)
	datejoined = db.DateTimeProperty(auto_now_add=True)
	user_karma = db.FloatProperty(default=1.0)
	email_hash = db.ComputedProperty(lambda e: hashlib.md5(e.useremail).hexdigest())

	@classmethod
	def by_id(cls, uid):
		return cls.get_by_id(uid)

	@classmethod
	def by_name(cls, useremail):
		u = cls.query().filter(cls.useremail == useremail).get()
		return u

	@classmethod
	def by_stripe_id(cls, sid):
		u = cls.query().filter(cls.stripeID == sid).get()
		return u

	@classmethod
	def by_name_return_key_only(cls, useremail):
		u = cls.query().filter(cls.useremail == useremail).get(keys_only=True)
		return u

	@classmethod
	def register(cls, useremail, pw, fullname, user_type=""):
		pw_hash = secure.make_pw_hash(useremail, pw)
		return cls(userfullname=str(fullname),
		           useremail=str(useremail),
		           user_type=str(user_type),
		           pw_hash=str(pw_hash),
		           id=str(useremail)
		           )

	@classmethod
	def login(cls, useremail):
		u = useremail
		if u:
			return u


class Vote(db.Model):
	vote = db.IntegerProperty(default=0)


class Voter(db.Model):
	count = db.IntegerProperty(default=0)
	hasVoted = db.BooleanProperty(default=False)
	hasAddedQuote = db.BooleanProperty(default=False)
	karma = db.IntegerProperty(default=1)


def _get_or_create_user(useremail):
	if useremail is None or useremail == '':
		return None
	user = User.get_by_id(id=useremail)
	if user is None:
		user = User(id=useremail, useremail=useremail)
		user.put()
	return user


def _get_or_create_voter(user):
	voter = Voter.get_by_id(id=user.useremail)
	if voter is None:
		voter = Voter(id=user.useremail)
	return voter


def _get_or_create_counter(topic):
	counter = Counter.get_by_id(id=topic)
	if counter is None:
		counter = Counter(id=topic, counter=0)
	return counter


def get_progress(user):
	voter = _get_or_create_voter(user)
	return voter.hasVoted, voter.hasAddedQuote


def _set_progress_hasVoted(user):
	def txn():
		voter = _get_or_create_voter(user)
		if not voter.hasVoted:
			voter.hasVoted = True
			voter.put()

	db.transaction(txn)


def _unique_user(user, transact=True):
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

	return hashlib.md5(user.useremail + "|" + str(count)).hexdigest()


def add_quote(title, text, user, uri=None, _created=None, topic=None):
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
				quote=title,
				created=created,
				creator=user.key,
				creation_order=now.isoformat()[:19] + "|" + unique_user,
				uri=uri,
				text=text,
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
		quotes = Quote.query(db.AND(Quote.q_type == False, Quote.creation_order <= offset)).order(
			-Quote.creation_order).fetch(PAGE_SIZE + 1)

	if len(quotes) > PAGE_SIZE:
		extra = quotes[-1].creation_order
		quotes = quotes[:PAGE_SIZE]
	return quotes, extra


def get_quotes_by_topic(offset=None, topic=None):
	extra = None
	if topic is None and offset is None:
		quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == None)).order(-Quote.creation_order).fetch(
			PAGE_SIZE + 1)
	elif topic is None and offset is not None:
		quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == None, Quote.creation_order <= offset)).order(
			-Quote.creation_order).fetch(PAGE_SIZE + 1)
	elif topic is not None and offset is None:
		quotes = Quote.query(db.AND(Quote.q_type == False, Quote.topic == topic)).order(-Quote.creation_order).fetch(
			PAGE_SIZE + 1)
	else:
		quotes = Quote.query(db.AND(Quote.q_type == False, topic == topic, Quote.creation_order <= offset)).order(
			-Quote.creation_order).fetch(PAGE_SIZE + 1)

	if len(quotes) > PAGE_SIZE:
		extra = quotes[-1].creation_order
		quotes = quotes[:PAGE_SIZE]
	return quotes, extra


def get_quotes(page=0, topic=None):
	assert page >= 0
	assert page < 20
	extra = None
	if topic is None or topic == '':
		quotes = Quote.query().order(
			-Quote.rank).fetch(PAGE_SIZE + 1)
	else:
		quotes = Quote.query(Quote.topic == topic).order(-Quote.rank).fetch(PAGE_SIZE + 1)

	if len(quotes) > PAGE_SIZE:
		if page < 19:
			extra = quotes[-1]
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

	return int(hot(ups, downs, date))


def set_vote(quote_id, user, newvote, is_url_safe=True):
	if user is None:
		return

	def txn():
		voter = _get_or_create_voter(user)
		# if voter.hasVoted:
		#   return

		if is_url_safe:
			quote = db.Key(urlsafe=quote_id).get()
		else:
			quote = quote_id.get()
		if quote is None:
			return

		creator = quote.creator.get() if quote is not None and quote.creator is not None else None
		if creator is None or creator.useremail != user.useremail:
			voter.karma += 1
			if creator is not None:
				creator_voter = _get_or_create_voter(quote.creator.get())
				creator_voter.karma += newvote

		vote = Vote.get_by_id(id=user.useremail, parent=quote.key)
		if vote is None:
			vote = Vote(id=user.useremail, parent=quote.key)
		if vote.vote == newvote:
			return

		vote.vote = newvote

		quote.up_votes += 1 if vote.vote == 1 else 0
		quote.down_votes += 1 if vote.vote == -1 else 0

		quote.rank = rank_quote(quote.up_votes, quote.down_votes, datetime.datetime.now())
		db.put_multi([vote, quote, voter])
		memcache.set("vote|" + user.useremail + "|" + str(quote_id), vote.vote)

	db.transaction(txn, xg=True)
	_set_progress_hasVoted(user)


def voted(quote, user):
	val = 0
	if user:
		memcachekey = "vote|" + user.useremail + "|" + str(quote.key)
		val = memcache.get(memcachekey)
		if val is not None:
			return val
		vote = Vote.get_by_id(id=user.useremail, parent=quote.key)
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
			creator=user.key,
			creation_order=now.isoformat()[:19] + "|" + unique_user,
			parent=quote.key,
			q_type=True,
		)
		return db.put_multi([comment, voter])

	return db.transaction(txn, xg=True)


def get_trending_topics():
	return [t.key.id() for t in Counter.query().order(-Counter.counter).fetch(20)]
