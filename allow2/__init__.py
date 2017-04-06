import human_curl as requests

def test():
	r = requests.get('http://h.wrttn.me/basic-auth/test_username/test_password', auth=('test_username', 'test_password'))
	r.status_code

	r.content
