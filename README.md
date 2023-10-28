# securitas-direct-new-api
This repository contains the new securitas direct API that can be integrated in Home Assistant.

## Example configuration

```yaml
securitas:
  username: !secret securitas_direct_username
  password: !secret securitas_direct_password
  code: !secret securitas_direct_code
  country: ES
  check_alarm_panel: false # defaultValue:True | set to false for NOT to check the alarm each time. See features.
```

## Features

- List all your installations and add a panel into Home Assistant.
- Support Sentinel and add two sensor for each Sentinel in each installation you have. The sensor are temperature and humidity.
- If the option is set to False, the check_alarm will only check the last status that securitas have in their server instead of checking in the alarm itself. This will decrease the number of request that show in your account. In this is set to true and you arm or disarm the alarm not throught Home Assistant, this will likely show a different state. The default value is True.
- Added a new configuration panel to change some of the options that you set during the setup. Here is an screenshot.

![Options](./docs/images/options.png)

## Breaking changes

If you update the component, the domain has been changed from securitas_direct to securitas, so you need to change your configuration as well or Home Assistant will not found the integration.