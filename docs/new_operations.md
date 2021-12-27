# How to capture the json request and json response payload from my browser.

## **CAUTION, this is a dangerous procedure, please pause before posting anything online.**

Securitas direct has a new API, but not all the customers have the same features in their homes, that is why I may need your help implementing new operations in the API.

For example arming the panel is this json payload to the API.

```json
{
    "operationName": "xSArmPanel",
    "variables": {
        "request": "ARM1",
        "numinst": "",
        "panel": "SDVFAST",
        "currentStatus": ""
    },
    "query": "mutation xSArmPanel($numinst: String!, $request: ArmCodeRequest!, $panel: String!, $pin: String, $currentStatus: String) {\\n  xSArmPanel(numinst: $numinst, request: $request, panel: $panel, pin: $pin, currentStatus: $currentStatus) {\\n    res\\n    msg\\n    referenceId\\n  }\\n}\\n"
}
```

The response is something like that:

```json
{
    "data": {
        "xSArmPanel": {
            "res": "OK",
            "msg": "Su solicitud ha sido enviada",
            "referenceId": "OWP_______________________________"
        }
    }
}
```

Then after the request has been sent, there a new type of request to check status.

```json
{
    "operationName": "ArmStatus",
    "variables": {
        "request": "ARM1",
        "numinst": "",
        "panel": "SDVFAST",
        "currentStatus": "D",
        "referenceId": "OWP_______________________________",
        "counter": 1
    },
    "query": "query ArmStatus($numinst: String!, $request: ArmCodeRequest, $panel: String!, $referenceId: String!, $counter: Int!) {\\n  xSArmStatus(numinst: $numinst, panel: $panel, referenceId: $referenceId, counter: $counter, request: $request) {\\n    res\\n    msg\\n    status\\n    protomResponse\\n    protomResponseDate\\n    numinst\\n    requestId\\n    error {\\n      code\\n      type\\n      allowForcing\\n      exceptionsNumber\\n      referenceId\\n    }\\n  }\\n}\\n"
}
```

And the response to that status operation

```json
{
    "data": {
        "xSArmStatus": {
            "res": "WAIT",
            "msg": "Petición en proceso",
            "status": null,
            "protomResponse": null,
            "protomResponseDate": null,
            "numinst": null,
            "requestId": "_pollingStatus_",
            "error": null
        }
    }
}
```

## **CAUTION, this is a dangerous procedure.**

So if you want to help me create new operations I need you that you post in the issue those payloads.

The only issue is that those payloads may contains personal and potential personal information, so you need to clean that first.

You may want to remove these fields:

- numinst (Your installation number)
- referenceId (It may contains your login id)
- user
- password
