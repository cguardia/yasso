from webob import Request

from paste.request import get_cookies

class SimpleCookiePlugin(object):

    def __init__(self, cookie_name):
        self.cookie_name = cookie_name

    def identify(self, environ):
	request = Request(environ)
	params = request.params
	if not 'login' in params or not 'password' in params:
	    return None
	login = params['login']
	password = params['password']
        return {'login':login, 'password':password}

    def remember(self, environ, identity):
        cookie_value = '%(login)s:%(password)s' % identity
        cookie_value = cookie_value.encode('base64').rstrip()
        cookies = get_cookies(environ)
        existing = cookies.get(self.cookie_name)
        value = getattr(existing, 'value', None)
        if value != cookie_value:
            # return a Set-Cookie header
            set_cookie = '%s=%s; Path=/;' % (self.cookie_name, cookie_value)
            return [('Set-Cookie', set_cookie)]

    def forget(self, environ, identity):
        # return a expires Set-Cookie header
        expired = ('%s=""; Path=/; Expires=Sun, 10-May-1971 11:59:00 GMT' %
                   self.cookie_name)
        return [('Set-Cookie', expired)]

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, id(self))

def make_plugin(cookie_name='simple'):
    plugin = SimpleCookiePlugin(cookie_name)
    return plugin

