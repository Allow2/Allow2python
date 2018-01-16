import common

#----------------------------------------------------------------------
def pair(user, password, deviceToken, deviceName):
	""""""
    r = requests.post(a2appUrl + '/api/pairDevice', data={
        'user' : user,
        'pass' : password,
        'deviceToken' : deviceToken,
        'name' : deviceName
    })

    if (r.status_code == 404):
        raise Exception('Authentication Failed', 404)

    if (r.status_code != 200):
        raise Exception('Unexpected Error', r.status_code)

    json_response = json.loads(r.content)

    if json_response.get('error') or (not json_response.get('status')) or (json_response['status'] != 'success'):
        raise Exception(json_response['error'], 500)

    return json_response['userId'], json_response['pairId'], json_response['children']