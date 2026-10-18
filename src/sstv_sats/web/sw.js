/* Service worker: only here so pass alerts can be shown as notifications. Android Chrome (and
   installed web apps on iPhone) don't allow `new Notification()` from a page, only from a service
   worker registration. It doesn't cache anything. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Tapping an alert brings the pass predictor back to the front (or opens it).
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const page = all.find((c) => c.url.startsWith(self.registration.scope));
    if (page) return page.focus();
    return self.clients.openWindow(self.registration.scope);
  })());
});
