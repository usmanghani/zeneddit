from google.appengine.ext import webapp
import update_schema
from google.appengine.ext import deferred

class UpdateHandler(webapp.RequestHandler):
    def get(self):
        deferred.defer(update_schema.UpdateSchema)
        self.response.out.write('Schema migration successfully initiated.')

app = webapp.WSGIApplication([('/update_schema', UpdateHandler)])
