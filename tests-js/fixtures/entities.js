const ALL_FEATURES = 1 | 2 | 4 | 16 | 32;

export function makeAlarmEntity({
  state = "disarmed",
  supportedFeatures = ALL_FEATURES,
  codeArmRequired = false,
  codeFormat = null,
  forceArmAvailable = false,
  armExceptions = [],
  wafBlocked = false,
  refreshFailed = false,
  friendlyName = "Test Alarm",
} = {}) {
  return {
    state,
    attributes: {
      friendly_name: friendlyName,
      supported_features: supportedFeatures,
      code_arm_required: codeArmRequired,
      code_format: codeFormat,
      force_arm_available: forceArmAvailable,
      arm_exceptions: armExceptions,
      waf_blocked: wafBlocked,
      refresh_failed: refreshFailed,
    },
  };
}

export function makeCameraEntity({
  state = "idle",
  accessToken = "token-abc",
  entityPicture = null,
  friendlyName = "Test Camera",
} = {}) {
  const token = accessToken;
  return {
    state,
    attributes: {
      friendly_name: friendlyName,
      access_token: token,
      entity_picture: entityPicture || `/api/camera_proxy/camera.test?token=${token}`,
    },
  };
}

export function makeActivityLogEntity({
  events = [],
  friendlyName = "Test Activity Log",
  backgroundPolling = false,
} = {}) {
  return {
    state: String(events.length),
    attributes: {
      friendly_name: friendlyName,
      events,
      background_polling: backgroundPolling,
    },
  };
}
