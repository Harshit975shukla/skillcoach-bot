/* SkillCoach web app service worker (scope /web). It caches nothing private.
   1. Offline: a page that cannot load shows a generic offline notice, precached with its styles
      and icon. Pages, API responses, lessons, documents and videos always come from the network.
   2. Notifications: a push names only a reminder kind. The text below is fixed, so no topic, name
      or score reaches a lock screen, and a tap opens SkillCoach at /web, never a URL from a message. */
"use strict";
const CACHE = "skillcoach-web-v1";
const OFFLINE = "/web/offline";
const SHELL = [OFFLINE, "/static/dashboard.css", "/static/web.css", "/static/icon-192.png"];
const TEXT = {
  lesson: "Today's lesson is ready.",
  quiz: "Your quiz is ready.",
  weekly: "Your weekly assessment is ready.",
  review: "Your weekly review is ready.",
  mentor: "Your mentor sent you a note.",
  update: "There is something new for you in SkillCoach.",
};

self.addEventListener("install", event => {
  // Notifications must work even if the offline page could not be stored.
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  // Only this app's older caches are removed; nothing else on the origin is touched.
  event.waitUntil(caches.keys()
    .then(names => Promise.all(names.filter(name => name.startsWith("skillcoach-web-") && name !== CACHE)
      .map(name => caches.delete(name))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(async () => (await caches.match(OFFLINE)) || Response.error()));
    return;
  }
  // Only the offline page's own public styles and icon may come from the cache, and only when the
  // network fails. Everything else (APIs, lessons, documents, media) is never answered from here.
  const url = new URL(request.url);
  if (url.origin === self.location.origin && !url.search && SHELL.includes(url.pathname) && url.pathname !== OFFLINE) {
    event.respondWith(fetch(request).catch(async () => (await caches.match(url.pathname)) || Response.error()));
  }
});

self.addEventListener("push", event => {
  let kind = "";
  try {
    const data = event.data ? event.data.json() : null;
    if (data && typeof data.push === "string" && Object.prototype.hasOwnProperty.call(TEXT, data.push)) kind = data.push;
  } catch (error) {
    kind = "";
  }
  event.waitUntil(self.registration.showNotification("SkillCoach", {
    body: kind ? TEXT[kind] : "Open SkillCoach to continue.",
    tag: "skillcoach-" + (kind || "update"),
    icon: "/static/icon-192.png",
    badge: "/static/badge-72.png",
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  // Always the conversation at /web on this origin: focus it if open, else bring an open SkillCoach
  // page there, else open a new window. Nothing in the message chooses where to go.
  event.waitUntil((async () => {
    const home = new URL("/web", self.location.origin).href;
    const windows = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    const ours = windows.filter(client => {
      const url = new URL(client.url);
      return url.origin === self.location.origin && (url.pathname === "/web" || url.pathname.startsWith("/web/"));
    });
    const conversation = ours.find(client => new URL(client.url).pathname === "/web");
    if (conversation && "focus" in conversation) return conversation.focus();
    for (const client of ours) {
      if (!("navigate" in client)) continue;
      try {
        const moved = await client.navigate(home);
        if (moved) return moved.focus();
      } catch (error) {
        // A page this worker does not control cannot be navigated; open a window instead.
      }
    }
    return self.clients.openWindow(home);
  })());
});
