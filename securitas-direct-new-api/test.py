import apimanager
import time
from dataTypes import CheckAlarmStatus

def test():
    api:apimanager.ApiManager = apimanager.ApiManager("","","ES","es")
    succeed = api.login()
    if succeed :
        instalations = api.listInstalations()
        for item in instalations:
            referenceId: str = api.checkAlarm(item)
            time.sleep(5)
            alarmStatus:CheckAlarmStatus = api.checkAlarmStatus(item, referenceId)
            while alarmStatus.status == "WAIT":
                time.sleep(5)
                alarmStatus:CheckAlarmStatus = api.checkAlarmStatus(item, referenceId)

            print(alarmStatus)
test()