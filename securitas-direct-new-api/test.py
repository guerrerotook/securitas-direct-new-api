import apimanager

def test():
    api:apimanager.ApiManager = apimanager.ApiManager("","","es","ES")
    succeed = api.login()

test()