# PiyasaDesk - Render Free Test Deploy

Bu paket **test/canli demo** icindir; production icin degildir.

## Render ayarlari

- Service: Web Service
- Plan: Free
- Build Command: `pip install -r requirements.txt`
- Start Command: `bash start_render.sh`
- Health Check Path: `/api/health`

`render.yaml` kullanirsan bu ayarlar otomatik gelir.

## Onemli: Free plan veri kaliciligi

Render Free Web Service'in yerel diski gecicidir. Servis uykuya girdiginde,
yeniden basladiginda veya deploy oldugunda `data/store/` ve `data/raw/`
altinda o oturumda toplanan veriler kaybolabilir. Bu, demo/test icin kabul
edilebilir; 7 gunluk gercek retention testi icin kalici disk/VPS gerekir.

## Collector

`start_render.sh`, collector'i 300 saniyelik dongude ayri process olarak
calistirir; FastAPI/uvicorn ise web process olarak foreground'da kalir.

## Sembol evreni

Bu zipteki `data/universe.txt` dosyasini deploy oncesi kontrol et. Tam BIST
evreni isteniyorsa gercek evren dosyasini bununla degistir.
