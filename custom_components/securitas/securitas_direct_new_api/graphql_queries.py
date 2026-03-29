"""GraphQL query and mutation strings for the Securitas Direct API."""

VALIDATE_DEVICE_MUTATION = (
    "mutation mkValidateDevice($idDevice: String, "
    "$idDeviceIndigitall: String, "
    "$uuid: String, $deviceName: String, $deviceBrand: String, "
    "$deviceOsVersion: String, $deviceVersion: String) {\n"
    "  xSValidateDevice(idDevice: $idDevice, idDeviceIndigitall: "
    "$idDeviceIndigitall, uuid: $uuid, deviceName: $deviceName, deviceBrand: "
    "$deviceBrand, deviceOsVersion: $deviceOsVersion, deviceVersion: "
    "$deviceVersion) {\n    res\n    msg\n    hash\n    refreshToken\n"
    "    legals\n  }\n}\n"
)

REFRESH_LOGIN_MUTATION = (
    "mutation RefreshLogin($refreshToken: String!, $id: String!, $country: "
    "String!, $lang: String!, $callby: String!, $idDevice: String!, "
    "$idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: "
    "String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: "
    "String!, $deviceOsVersion: String!, $uuid: String!) {\n"
    "  xSRefreshLogin(refreshToken: $refreshToken, "
    "id: $id, country: $country, "
    "lang: $lang, callby: $callby, idDevice: $idDevice, idDeviceIndigitall: "
    "$idDeviceIndigitall, deviceType: $deviceType, deviceVersion: "
    "$deviceVersion, deviceResolution: $deviceResolution, deviceName: "
    "$deviceName, deviceBrand: $deviceBrand, deviceOsVersion: "
    "$deviceOsVersion, uuid: $uuid) {\n    __typename\n    res\n    msg\n"
    "    hash\n    refreshToken\n    legals\n    changePassword\n"
    "    needDeviceAuthorization\n    mainUser\n  }\n}"
)

SEND_OTP_MUTATION = (
    "mutation mkSendOTP($recordId: Int!, $otpHash: String!) {\n"
    "  xSSendOtp(recordId: $recordId, otpHash: $otpHash) {\n    res\n    msg\n"
    "  }\n}\n"
)

LOGIN_TOKEN_MUTATION = (
    "mutation mkLoginToken($user: String!, $password: String!, $id: String!, "
    "$country: String!, $lang: String!, $callby: String!, $idDevice: String!, "
    "$idDeviceIndigitall: String!, $deviceType: String!, $deviceVersion: "
    "String!, $deviceResolution: String!, $deviceName: String!, $deviceBrand: "
    "String!, $deviceOsVersion: String!, $uuid: String!) { xSLoginToken(user: "
    "$user, password: $password, country: $country, lang: $lang, callby: "
    "$callby, id: $id, idDevice: $idDevice, idDeviceIndigitall: "
    "$idDeviceIndigitall, deviceType: $deviceType, deviceVersion: "
    "$deviceVersion, deviceResolution: $deviceResolution, deviceName: "
    "$deviceName, deviceBrand: $deviceBrand, deviceOsVersion: "
    "$deviceOsVersion, uuid: $uuid) { __typename res msg hash refreshToken "
    "legals changePassword needDeviceAuthorization mainUser } }"
)

INSTALLATION_LIST_QUERY = (
    "query mkInstallationList {\n  xSInstallations {\n    installations {\n"
    "      numinst\n      alias\n      panel\n      type\n      name\n"
    "      surname\n      address\n      city\n      postcode\n"
    "      province\n      email\n      phone\n    }\n  }\n}\n"
)

CHECK_ALARM_QUERY = (
    "query CheckAlarm($numinst: String!, $panel: String!) {\n"
    "  xSCheckAlarm(numinst: $numinst, panel: $panel) {\n    res\n    msg\n"
    "    referenceId\n  }\n}\n"
)

SERVICES_QUERY = (
    "query Srv($numinst: String!, $uuid: String) {\n"
    "  xSSrv(numinst: $numinst, uuid: $uuid) {\n    res\n    msg\n"
    "    language\n    installation {\n      numinst\n      role\n"
    "      alias\n      status\n      panel\n      sim\n      instIbs\n"
    "      services {\n        idService\n        active\n        visible\n"
    "        bde\n        isPremium\n        codOper\n        request\n"
    "        minWrapperVersion\n        unprotectActive\n"
    "        unprotectDeviceStatus\n        instDate\n"
    "        genericConfig {\n          total\n          attributes {\n"
    "            key\n            value\n          }\n        }\n"
    "        attributes {\n          attributes {\n            name\n"
    "            value\n            active\n          }\n        }\n      }\n"
    "      configRepoUser {\n        alarmPartitions {\n          id\n"
    "          enterStates\n          leaveStates\n        }\n      }\n"
    "      capabilities\n    }\n  }\n}"
)

SENTINEL_QUERY = (
    "query Sentinel($numinst: String!) {\n  xSComfort(numinst: $numinst) {\n"
    "    res\n    devices {\n      alias\n      status {\n"
    "        temperature\n        humidity\n        airQualityCode\n      }\n"
    "      zone\n    }\n    forecast {\n      city\n      currentHum\n"
    "      currentTemp\n      forecastCode\n      forecastedDays {\n"
    "        date\n        forecastCode\n        maxTemp\n        minTemp\n"
    "      }\n    }\n  }\n}"
)

AIR_QUALITY_QUERY = (
    "query AirQuality($numinst: String!, $zone: String!) {\n"
    "  xSAirQuality(numinst: $numinst, zone: $zone) {\n    res\n    data {\n"
    "      status {\n        current\n        avg6h\n        avg24h\n"
    "        avg7d\n        avg4w\n      }\n      hours {\n        id\n"
    "        value\n      }\n    }\n  }\n}"
)

GENERAL_STATUS_QUERY = (
    "query Status($numinst: String!) {\n  xSStatus(numinst: $numinst) {\n"
    "    status\n    timestampUpdate\n    wifiConnected\n    exceptions {\n"
    "      status\n      deviceType\n      alias\n    }\n  }\n}"
)

CHECK_ALARM_STATUS_QUERY = (
    "query CheckAlarmStatus($numinst: String!, $idService: String!, $panel: "
    "String!, $referenceId: String!) {\n"
    "  xSCheckAlarmStatus(numinst: $numinst, idService: $idService, panel: "
    "$panel, referenceId: $referenceId) {\n    res\n    msg\n    status\n"
    "    numinst\n    protomResponse\n    protomResponseDate\n  }\n}\n"
)

ARM_STATUS_QUERY = (
    "query ArmStatus($numinst: String!, $request: ArmCodeRequest,"
    " $panel: String!, $referenceId: String!, $counter: Int!,"
    " $forceArmingRemoteId: String, $armAndLock: Boolean) {\n"
    "  xSArmStatus(numinst: $numinst, panel: $panel,"
    " referenceId: $referenceId, counter: $counter, request: $request,"
    " forceArmingRemoteId: $forceArmingRemoteId,"
    " armAndLock: $armAndLock) {\n"
    "    res\n    msg\n    status\n    protomResponse\n"
    "    protomResponseDate\n    numinst\n    requestId\n"
    "    error {\n      code\n      type\n      allowForcing\n"
    "      exceptionsNumber\n      referenceId\n      suid\n    }\n"
    "  }\n}\n"
)

GET_EXCEPTIONS_QUERY = (
    "query xSGetExceptions($numinst: String!, $panel: String!,"
    " $referenceId: String!, $counter: Int!, $suid: String) {\n"
    "  xSGetExceptions(numinst: $numinst, panel: $panel,"
    " referenceId: $referenceId, counter: $counter, suid: $suid) {\n"
    "    res\n    msg\n"
    "    exceptions {\n      status\n      deviceType\n      alias\n    }\n"
    "  }\n}\n"
)

DISARM_STATUS_QUERY = (
    "query DisarmStatus($numinst: String!, $panel: String!, $referenceId: "
    "String!, $counter: Int!, $request: DisarmCodeRequest) {\n"
    "  xSDisarmStatus(numinst: $numinst, panel: $panel, referenceId: "
    "$referenceId, counter: $counter, request: $request) {\n    res\n    msg\n"
    "    status\n    protomResponse\n    protomResponseDate\n    numinst\n"
    "    requestId\n    error {\n      code\n      type\n      allowForcing\n"
    "      exceptionsNumber\n      referenceId\n    }\n  }\n}\n"
)

SMARTLOCK_CONFIG_QUERY = (
    "query xSGetSmartlockConfig($numinst: String!, $panel: String!, "
    "$deviceId: String, $keytype: String, $deviceType: String) {\n"
    "  xSGetSmartlockConfig(\n    numinst: $numinst\n    panel: $panel\n"
    "    deviceId: $deviceId\n    keytype: $keytype\n"
    "    deviceType: $deviceType\n  ) {\n    res\n    referenceId\n"
    "    zoneId\n    serialNumber\n    location\n    family\n    label\n"
    "    features {\n      holdBackLatchTime\n      calibrationType\n"
    "      autolock {\n        active\n        timeout\n      }\n"
    "    }\n  }\n}"
)

LOCK_CURRENT_MODE_QUERY = (
    "query xSGetLockCurrentMode($numinst: String!, $counter: Int) {\n"
    "  xSGetLockCurrentMode(numinst: $numinst, counter: $counter) {\n    res\n"
    "    smartlockInfo {\n      lockStatus\n      deviceId\n"
    "      statusTimestamp\n    }\n  }\n}"
)

CHANGE_LOCK_MODE_STATUS_QUERY = (
    "query xSChangeSmartlockModeStatus($numinst: String!, $panel: String!, "
    "$referenceId: String!, $deviceId: String, $counter: Int) {\n"
    "  xSChangeSmartlockModeStatus(\n    numinst: $numinst\n"
    "    panel: $panel\n    referenceId: $referenceId\n    counter: $counter\n"
    "    deviceId: $deviceId\n  ) {\n    res\n    msg\n    protomResponse\n"
    "    status\n  }\n}"
)

ARM_PANEL_MUTATION = (
    "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!,"
    " $panel: String!, $currentStatus: String, $suid: String,"
    " $forceArmingRemoteId: String, $armAndLock: Boolean) {\n"
    "  xSArmPanel(numinst: $numinst, request: $request, panel: $panel,"
    " currentStatus: $currentStatus, suid: $suid,"
    " forceArmingRemoteId: $forceArmingRemoteId,"
    " armAndLock: $armAndLock) {\n"
    "    res\n    msg\n    referenceId\n  }\n}\n"
)

DISARM_PANEL_MUTATION = (
    "mutation xSDisarmPanel($numinst: String!, $request: DisarmCodeRequest!, "
    "$panel: String!) {\n"
    "  xSDisarmPanel(numinst: $numinst, request: $request, panel: $panel) {\n"
    "    res\n    msg\n    referenceId\n  }\n}\n"
)

CHANGE_LOCK_MODE_MUTATION = (
    "mutation xSChangeSmartlockMode($numinst: String!, $panel: String!, "
    "$deviceId: String!, $deviceType: String!, $lock: Boolean!) {\n"
    "  xSChangeSmartlockMode(\n    numinst: $numinst\n    panel: $panel\n"
    "    deviceId: $deviceId\n    deviceType: $deviceType\n    lock: $lock\n"
    "  ) {\n    res\n    msg\n    referenceId\n  }\n}"
)

DEVICE_LIST_QUERY = (
    "query xSDeviceList($numinst: String!, $panel: String!) {"
    " xSDeviceList(numinst: $numinst, panel: $panel) {"
    " res devices { id code zoneId name type isActive serialNumber }"
    " } }"
)

REQUEST_IMAGES_MUTATION = (
    "mutation RequestImages($numinst: String!, $panel: String!,"
    " $devices: [Int]!, $mediaType: Int, $resolution: Int,"
    " $deviceType: Int) {"
    " xSRequestImages(numinst: $numinst, panel: $panel,"
    " devices: $devices, mediaType: $mediaType,"
    " resolution: $resolution, deviceType: $deviceType) {"
    " res msg referenceId } }"
)

REQUEST_IMAGES_STATUS_QUERY = (
    "query RequestImagesStatus($numinst: String!, $panel: String!,"
    " $devices: [Int!]!, $referenceId: String!, $counter: Int) {"
    " xSRequestImagesStatus(numinst: $numinst, panel: $panel,"
    " devices: $devices, referenceId: $referenceId,"
    " counter: $counter) { res msg numinst status } }"
)

GET_THUMBNAIL_QUERY = (
    "query mkGetThumbnail($numinst: String!, $panel: String!,"
    " $device: String, $zoneId: String, $idSignal: String) {"
    " xSGetThumbnail(numinst: $numinst, device: $device,"
    " panel: $panel, zoneId: $zoneId, idSignal: $idSignal) {"
    " idSignal deviceId deviceCode deviceAlias timestamp"
    " signalType image type quality } }"
)

GET_PHOTO_IMAGES_QUERY = (
    "query mkGetPhotoImages($numinst: String!, $idSignal: String!,"
    " $signalType: String!, $panel: String!) {"
    " xSGetPhotoImages(numinst: $numinst, idsignal: $idSignal,"
    " signaltype: $signalType, panel: $panel) {"
    " devices { id idSignal code name quality"
    " images { id image type } } } }"
)

DANALOCK_CONFIG_QUERY = (
    "query xSGetDanalockConfig($numinst: String!, $panel: String!,"
    " $deviceId: String!, $deviceType: String!) {\n"
    "  xSGetDanalockConfig(\n    numinst: $numinst\n    panel: $panel\n"
    "    deviceId: $deviceId\n    deviceType: $deviceType\n"
    "  ) {\n    res\n    msg\n    referenceId\n  }\n}"
)

DANALOCK_CONFIG_STATUS_QUERY = (
    "query xSGetDanalockConfigStatus($numinst: String!,"
    " $referenceId: String!, $counter: Int!) {\n"
    "  xSGetDanalockConfigStatus(\n    numinst: $numinst\n"
    "    referenceId: $referenceId\n    counter: $counter\n"
    "  ) {\n    res\n    msg\n    deviceNumber\n"
    "    features {\n      holdBackLatchTime\n      calibrationType\n"
    "      autolock {\n        active\n        timeout\n      }\n"
    "    }\n  }\n}"
)
