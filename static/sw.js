const CACHE_NAME = 'undercover-v1';
const ASSETS = [
    '/',
    '/static/manifest.json',
    '/static/icon.svg',
    '/static/hotseat.html',
    'https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800;900&display=swap'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(ASSETS);
        })
    );
});

self.addEventListener('fetch', event => {
    // Only intercept GET requests
    if (event.request.method !== 'GET') return;

    // API calls bypass cache for offline resilience message
    if (event.request.url.includes('/api/')) {
        event.respondWith(
            fetch(event.request).catch(() => {
                return new Response(JSON.stringify({error: "Vous êtes hors-ligne. Vérifiez votre connexion pour synchroniser avec le serveur."}), {
                    headers: { 'Content-Type': 'application/json' }
                });
            })
        );
        return;
    }

    // Static assets
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
