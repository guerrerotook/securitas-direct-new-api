// The More Info module defines its element once HA's app element exists.
export async function importMoreInfo() {
  if (!customElements.get("home-assistant")) {
    customElements.define("home-assistant", class extends HTMLElement {});
  }
  await import("../../custom_components/securitas/www/verisure-owa-more-info.js");
  await customElements.whenDefined("more-info-verisure-owa-alarm");
}
