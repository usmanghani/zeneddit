import random
import hashlib
import hmac
from string import letters

#secret key (should be in a different file for production)
secret = "lalkjas~!@poi2lsjf@#TUSIZ"

####GLOBAL HASHING FUNCTIONS

###This part implements hashed cookies on the site

#This function creates a hash string; returns "value|HASH" using HMAC
#to store as a cookie
def make_secure_val(val):
	return '%s|%s' % (val, hmac.new(secret, val).hexdigest())

#This function checks if cookie value is untampered by splitting the string at | and 
#comparing the value (first part) is same as its HASH value (second part of cookie)
def check_secure_val(secure_val):
	val = secure_val.split('|')[0] #returns original value
	if secure_val == make_secure_val(val):
		return val

###This part related to hashing passwords
def make_salt(length = 5):
	return ''.join(random.choice(letters) for x in xrange(length))

def make_pw_hash(name, pw, salt = None):
	if not salt:
		salt = make_salt()
	h = hashlib.sha256(name + pw + salt).hexdigest()
	return '%s, %s' % (salt, h)

def valid_pw(name, password, h):
	salt = h.split(',')[0]
	return h == make_pw_hash(name, password, salt)