/*
 * Service worker -- SADECE "yuklenebilir uygulama" olmak icin var.
 *
 * KRITIK TASARIM KARARI: HICBIR SEY ONBELLEGE ALINMIYOR.
 * Bu bir haber takip araci; onbellek demek BAYAT HABER demek. Klasik
 * PWA service worker'lari kabugu (shell) cache'ler ve API'yi
 * network-first yapar -- ama burada kabuk da API de ayni yerel
 * sunucudan geliyor, dolayisiyla cache hicbir sey kazandirmaz, sadece
 * "neden eski haber goruyorum" hatasi riski getirir.
 *
 * Bu yuzden fetch handler yok: her istek dogrudan aga (yerel sunucuya)
 * gider. Chrome/Edge yuklenebilirlik icin kayitli bir service worker
 * arar; bu dosya o sarti karsilar, davranisi degistirmez.
 */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
