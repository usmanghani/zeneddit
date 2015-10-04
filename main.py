import cgi
import logging
import os
import urlparse
import webapp2
from google.appengine.api import users
from google.appengine.ext.webapp import template
import models
import wsgiref.handlers
import urllib
import urllib2
import json


def get_login_url(default=True):
	if default:
		return cgi.escape(users.create_login_url("/"))
	else:
		return ("https://secure.zenefits.com/oauth2/login/?next=" +
		        urllib.quote(
			        "/oauth2/authorize/?client_id=CGZOt4fCPtBDPFB8oSWEg6UWNlNPWs8KNNGZ5OXh&state=random_state_string&response_type=code&scope=read&redirect_uri=" +
			        os.environ['REDIRECT_URL']))


def get_greeting(user):
	progress_id = 1
	progress_msg = 'You get karma just for showing up.'
	if user:
		voter = models._get_or_create_voter(user)
		greeting = ('%s (%d) (<a class="loggedin" href="%s">sign out</a>)' %
		            (user.useremail, voter.karma, cgi.escape(('/logout'))))
		progress_id = 3
		progress_msg = 'More karma for logging in.'
		has_voted, has_added_quote = models.get_progress(user)
		if has_voted:
			progress_id |= 4
			progress_msg = ""
		if has_added_quote:
			progress_id |= 8
			progress_msg = ""
	else:
		greeting = (u"<a  href=\"%s\">Sign in to create or vote</a>." % get_login_url(default=False))
	return (progress_id, progress_msg, greeting)


def quote_for_template(quotes, user, page=0):
	quotes_tpl = []
	index = 1 + page * models.PAGE_SIZE
	for quote in quotes:
		quotes_tpl.append({
			'id': quote.key.urlsafe(),
			'uri': quote.uri,
			'voted': models.voted(quote, user),
			'quote': quote.quote,
			'creator': quote.creator,
			'created': quote.creation_order[:10],
			'created_long': quote.creation_order[:19],
			'votesum': quote.votesum,
			'up_votes': quote.up_votes,
			'down_votes': quote.down_votes,
			'index': index,
			'topic': quote.topic if quote.topic else 'General',
			'rank': quote.rank,
		})
		index += 1
	return quotes_tpl


def create_template_dict(user, quotes, section, nexturi=None, prevuri=None, page=0, comments=[]):
	progress_id, progress_msg, greeting = get_greeting(user)
	template_values = {
		'progress_id': progress_id,
		'progress_msg': progress_msg,
		'greeting': greeting,
		'loggedin': user.useremail if user is not None else None,
		'quotes': quote_for_template(quotes, user, page),
		'trending': models.get_trending_topics(),
		'section': section,
		'nexturi': nexturi,
		'prevuri': prevuri,
		'comments': quote_for_template(comments, user, page),
	}

	return template_values


class LogoutHandler(webapp2.RequestHandler):
	def get(self):
		self.response.headers.add_header('Set-Cookie', 'u_id=; Path=/')
		self.redirect('/')


class MainHandler(webapp2.RequestHandler):
	def get(self):
		return self._get_impl(topic=None)

	def _get_impl(self, topic):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		page = int(self.request.get('p', '0'))
		quotes, next = models.get_quotes(page, topic)
		if next:
			nexturi = '/?p=%d' % (page + 1)
		else:
			nexturi = None
		if page > 1:
			prevuri = '/?p=%d' % (page - 1)
		elif page == 1:
			prevuri = '/'
		else:
			prevuri = None

		template_values = create_template_dict(
			user, quotes, topic or 'Popular', nexturi, prevuri, page
		)
		template_file = os.path.join(os.path.dirname(__file__), 'templates/index.html')
		self.response.out.write(unicode(template.render(template_file, template_values)))

	def post(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		text = self.request.get('newtidbit').strip()
		if len(text) > 500:
			text = text[:500]
		uri = self.request.get('tidbituri').strip()

		if not text and not uri:
			logging.info("No text or uri was submitted.")
			self.redirect('/')
			return

		topic = self.request.get('tidbittopic').strip()
		title = self.request.get('tidbittitle').strip()
		parsed_uri = urlparse.urlparse(uri)

		progress_id, progress_msg, greeting = get_greeting(user)

		if uri and (not parsed_uri.scheme or not parsed_uri.netloc):
			template_values = {
				'progress_id': progress_id,
				'progress_msg': progress_msg,
				'greeting': greeting,
				'loggedin': user,
				'title': title,
				'text': text,
				'uri': uri,
				'topic': topic,
				'error_msg': 'The supplied link is not a valid absolute URI'
			}
			template_file = os.path.join(os.path.dirname(__file__),
			                             'templates/add_quote_error.html'
			                             )
			self.response.out.write(unicode(template.render(template_file, template_values)))
		else:
			quote_id = models.add_quote(title, text, user, uri=uri, topic=topic)
			if quote_id is not None:
				models.set_vote(quote_id, user, 1, is_url_safe=False)
				self.redirect('/z/' + topic)
			else:
				template_values = {
					'progress_id': progress_id,
					'progress_msg': progress_msg,
					'greeting': greeting,
					'loggedin': user,
					'title': title,
					'text': text,
					'uri': uri,
					'topic': topic,
					'error_msg': 'An error occured while adding this quote, please try again.'
				}
				template_file = os.path.join(os.path.dirname(__file__),
				                             'templates/add_quote_error.html'
				                             )
				self.response.out.write(unicode(template.render(template_file, template_values)))


class SubmitLinkPostHandler(MainHandler):
	def get(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		offset = self.request.get('offset')
		page = int(self.request.get('p', '0'))
		logging.info('Latest offset = %s' % offset)
		if not offset:
			offset = None
		quotes, next = models.get_quotes_newest(offset)
		if next:
			nexturi = '?offset=%s&p=%d' % (next, page + 1)
		else:
			nexturi = None

		if user:
			template_values = create_template_dict(user, quotes, 'Recent', nexturi, prevuri=None, page=page)
			template_file = os.path.join(os.path.dirname(__file__), 'templates/base_submit.html')
			self.response.out.write(unicode(template.render(template_file, template_values)))
		else:
			login_url = get_login_url(default=False)
			self.redirect(login_url)


class SubmitTextPostHandler(MainHandler):
	"""Handles Submissions"""

	def get(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		offset = self.request.get('offset')
		page = int(self.request.get('p', '0'))
		logging.info('Latest offset = %s' % offset)
		if not offset:
			offset = None
		quotes, next = models.get_quotes_newest(offset)
		if next:
			nexturi = '?offset=%s&p=%d' % (next, page + 1)
		else:
			nexturi = None

		template_values = create_template_dict(user, quotes, 'Recent', nexturi, prevuri=None, page=page)
		template_file = os.path.join(os.path.dirname(__file__), 'templates/base_submittext.html')
		self.response.out.write(unicode(template.render(template_file, template_values)))


class NewZennitHandler(MainHandler):
	def post(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		name = self.request.get('zennitname').strip()
		description = self.request.get('zennitdescription')
		if len(description) > 1000:
			description = description[:1000]

		if not name or description:
			logging.info("No name or description was submitted.")
			self.redirect('/')
		else:
			zennit_id = models.add_zennit(name, description, user)
			if zennit_id is not None:
				self.redirect('/z/' + zennit_id)
			else:
				self.response.out.write(unicode("Error creating zennit."))

	def get(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		offset = self.request.get('offset')
		page = int(self.request.get('p', '0'))
		logging.info('Latest offset = %s' % offset)
		if not offset:
			offset = None
		quotes, next = models.get_quotes_newest(offset)
		if next:
			nexturi = '?offset=%s&p=%d' % (next, page + 1)
		else:
			nexturi = None

		template_values = create_template_dict(user, quotes, 'Recent', nexturi, prevuri=None, page=page)
		template_file = os.path.join(os.path.dirname(__file__), 'templates/base_newzennit.html')
		self.response.out.write(unicode(template.render(template_file, template_values)))

class TopicHandler(MainHandler):
	def get(self, topic):
		return super(TopicHandler, self)._get_impl(topic=topic)


class VoteHandler(webapp2.RequestHandler):
	def post(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))
		if user is None:
			self.response.set_status(403, 'Forbidden')
			return
		quoteid = self.request.get('quoteid')
		vote = self.request.get('vote')
		if not vote in ['1', '-1']:
			self.response.set_status(400, 'Bad Request')
			return
		vote = int(vote)
		models.set_vote(quoteid, user, vote)
		self.redirect('')


class RecentHandler(webapp2.RequestHandler):
	def get(self):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		offset = self.request.get('offset')
		page = int(self.request.get('p', '0'))
		logging.info('Latest offset = %s' % offset)
		if not offset:
			offset = None
		quotes, next = models.get_quotes_newest(offset)
		if next:
			nexturi = '?offset=%s&p=%d' % (next, page + 1)
		else:
			nexturi = None

		template_values = create_template_dict(user, quotes, 'Recent', nexturi, prevuri=None, page=page)
		template_file = os.path.join(os.path.dirname(__file__), 'templates/recent.html')
		self.response.out.write(unicode(template.render(template_file, template_values)))


class FeedHandler(webapp2.RequestHandler):
	def get(self, section):
		user = None
		if section == 'recent':
			quotes, next = models.get_quotes_newest()
		elif section == 'popular':
			quotes, next = models.get_quotes()
		else:
			self.response.set_status(404, 'Not Found')
			return

		template_values = create_template_dict(user, quotes, section.capitalize())
		template_file = os.path.join(os.path.dirname(__file__), 'templates/atom_feed.xml')
		self.response.headers['Content-Type'] = 'application/atom+xml; charset=utf-8'
		self.response.out.write(unicode(template.render(template_file, template_values)))


class QuoteHandler(webapp2.RequestHandler):
	def post(self, quoteid):
		user = models._get_or_create_user(self.request.cookies.get('u_id'))

		quote = models.get_quote(quoteid)
		models.comment_on_quote(quote, user, self.request.get('newcomment'))
		self.redirect('')

	def get(self, quoteid):
		"""Get a page for just the quote identified."""
		quote = models.get_quote(quoteid)
		if quote is None:
			self.response.set_status(404, 'Not Found')
			return
		user = models._get_or_create_user(self.request.cookies.get('u_id'))
		quotes = [quote]
		comments = models.get_comments_for_quote(quote.key)
		template_values = create_template_dict(user, quotes, 'Quote', nexturi=None, prevuri=None, page=0,
		                                       comments=comments)
		template_file = os.path.join(os.path.dirname(__file__), 'templates/singlequote.html')
		self.response.out.write(unicode(template.render(template_file, template_values)))


class TrendingHandler(webapp2.RequestHandler):
	def get(self):
		return self.response.out.write(unicode(models.get_trending_topics()))


class OAuthHandler(webapp2.RequestHandler):
	def get(self):
		code = self.request.get('code')
		if code is not None:
			req = urllib2.Request('https://secure.zenefits.com/oauth2/token/', data=urllib.urlencode({
				'grant_type': 'authorization_code',
				'client_id': 'CGZOt4fCPtBDPFB8oSWEg6UWNlNPWs8KNNGZ5OXh',
				'client_secret': 'fDdLLsSF6gazcogc11XpsXaxoG6YXp8tvIPxkUqFC1aJwgrGLjtNF4RPoRzieZmdA9Wz3vTSuGJySVNNVFKC8bPYO2o03ETupaLkkd2AWjn3VWBjp8V0jA08ijPSFPuN',
				'redirect_uri': os.environ['REDIRECT_URL'],
				'code': code
			}))
			response = urllib2.urlopen(req)
			response_data = response.read()
			json_data = json.loads(response_data)
			access_token = json_data['access_token']
			req = urllib2.Request('https://secure.zenefits.com/oauth2/me/',
			                      headers={'Authorization': 'Bearer ' + access_token})
			response = urllib2.urlopen(req)
			response_data = response.read()
			json_data = json.loads(response_data)
			logging.info(json_data['email'])
			self.response.headers.add_header('Set-Cookie', '%s=%s; Path=/' % ('u_id', str(json_data['email'])))
			self.redirect('/')
		else:
			self.response.out.write(unicode("I AM SAD!"))


application = webapp2.WSGIApplication(
	[
		('/', MainHandler),
		('/submit', SubmitLinkPostHandler),
		('/logout', LogoutHandler),
		('/submittext', SubmitTextPostHandler),
		('/newzennit', NewZennitHandler),
		('/vote/', VoteHandler),
		('/recent/', RecentHandler),
		('/post/(.*)', QuoteHandler),
		('/feed/(recent|popular)/', FeedHandler),
		('/z/(.*)', TopicHandler),
		('/trending', TrendingHandler),
		('/oauth_callback', OAuthHandler),
	], debug=True)


def main():
	wsgiref.handlers.CGIHandler().run(application)


if __name__ == '__main__':
	main()
