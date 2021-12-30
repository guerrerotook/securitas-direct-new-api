# securitas-direct-new-api
This repository contains the new securitas direct API that can be integrated in Home Assistant.

## Example configuration

```yaml
securitas_direct:
  username: !secret securitas_direct_username
  password: !secret securitas_direct_password
  code: !secret securitas_direct_code
  country: ES
```

## Features

- List all your installations and add a panel into Home Assistant.
- Support Sentinel and add two sensor for each Sentinel in each installation you have. The sensor are temperature and humidity.
