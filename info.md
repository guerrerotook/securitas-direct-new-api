# Verisure OWA

A Home Assistant custom integration for **Verisure** (formerly Securitas Direct in some markets), supporting Argentina, Brazil, Chile, France, Ireland, Italy, Peru, Portugal, Spain, and the United Kingdom.

Renamed from `securitas` to `verisure_owa` in v5.0.0. The legacy domain shim, service aliases, event aliases, and panel URL aliases remain available during a 6-month deprecation window. See the v5 release notes for migration details.

## Features

- List all your installations and add a panel into Home Assistant.
- Support Sentinel and add two sensor for each Sentinel in each installation you have. The sensor are temperature and humidity.

## Breaking changes

If you update the component, the domain has been changed from `securitas` to `verisure_owa` in v5.0.0. A legacy shim handles automatic migration. See the v5 release notes for details.
