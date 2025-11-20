# Futures Bot Paneli - Premium Arayüz Uygulama Planı

Bu doküman, mevcut (tailwind + Alpine.js) paneli premium, tutarlı ve okunabilir bir görünüme taşımak için uygulanacak adımları özetler. Mevcut HTML iskeleti ve snippet'ler bu plana referans alınarak güncellenecek.

## Hedefler
- Bybit tarzı karanlık/aydınlık tema desteği ve tutarlı renk paleti.
- Kart, tablo, sekme, modal ve bildirim bileşenlerinde hiyerarşi ve boşluk düzeni.
- Dashboard ve trade akışında hızlı okunabilir metrik kartları, rozetler ve ikonografi.
- Strategy/Webhook, Risk grafikleri ve Simulation alanında responsive grid ve net tipografi.
- Bildirim/Toast/Modal alanlarında sadeleştirilmiş görsel dil ve tutarlı animasyonlar.

## Dosya Yapısı ve Gerekli Noktalar
- **Template**: `templates/index.html` (veya mevcut HTML dosyası). Tailwind sınıfları modernize edilecek, layout yeniden gruplanacak.
- **Stil**: `static/css/app.css` (Tailwind utility desteği + özel sınıflar). Temalar ve bileşen varyantları burada tanımlanacak.
- **İstemci Mantığı**: `static/js/app.js` (Alpine.js durum yönetimi + tema toggle). Yeni sınıf/tema bağlamları eklenecek.
- **Sunucu**: HTML’yi dönen Python dosyası (örn. `app.py` veya `main.py`) — route ismi ve render yöntemi doğrulanmalı.

## Uygulama Adımları
1. **Tema ve Palet**: Tailwind için kök değişkenler tanımla (`--bg`, `--surface`, `--text`, `--accent`). Koyu/açık tema geçişini `data-theme` ile senkronize et.
2. **Layout Temizliği**: Navbar, sekmeler ve arama/aksiyon barlarını `flex`/`grid` ile hizala; kartlara gölge ve radius ekle; spacing ölçeğini standartlaştır.
3. **Dashboard Kartları**: Günlük PnL, toplam PnL, ROI ve risk limiti kartlarına renk kodu (yeşil/kırmızı) ve küçük ikon ekle; BTC özet kartında iki kolonlu grid.
4. **Trade Paneli**: Filtre barını chip tarzına çevir; pozisyon kartlarını iki kolon grid + header/footerdaki buton stillerini hizala; boş durum mesajı sadeleştir.
5. **Risk & Chart Bölümü**: Chart container’larına sabit yükseklik, grid boşlukları ve başlık tipografisi ekle.
6. **Simulation**: Form alanlarını iki kolon/grid yapısına getir; sonuç tablosu için zebra satırlar ve sticky header; örnek senaryo butonu ikincil aksiyon olarak bırak.
7. **Strategy/Webhook**: Webhook URL kutusu, örnek payload ve test formunu kart içinde üçlü blok olarak hizala; `copy` butonuna geribildirim ekle.
8. **Users & Settings**: Tablo ve form elemanlarını aynı spacing ve badge sistemine bağla; toggle stillerini güncelle.
9. **Logs & Notifications**: Log paneli için monospaced font ve satır aralığı; notification center ve toast’larda renk şeritleri ve kapanma animasyonları.
10. **Erişilebilirlik ve Responsive**: Klavye odak stilleri, kontrast sınaması; mobilde sekmeler scrollable, kartlar tek kolon.

## Test & Doğrulama
- Sunucuyu (örn. `flask run`) çalıştırıp sayfanın tüm sekmelerini manuel kontrol et.
- Tema geçişi, webhook test formu ve CSV export gibi aksiyonları tıkla; konsolda hata olmadığını doğrula.
- Lighthouse veya benzeri bir aracın hızlı denetimiyle kontrast ve performans sorunlarını gözden geçir.

## İhtiyaç Duyulan Bilgi
- Kullanılan gerçek template yolu ve Python entrypoint (route’lar). Bunlar olmadan değişiklikleri doğru dosyaya uygulamak mümkün olmayabilir.
- Tailwind derleme süreci (CDN mi postcss mi?). Mevcut snippet CDN kullanıyor; özel stiller `app.css` altında yazılacak.

## Kısaca ne yapmalıyım?
- Bu planı bir “yol haritası” olarak kullan: `templates/index.html`, `static/css/app.css` ve `static/js/app.js` dosyalarını açıp adım adım güncelle.
- Cursor gibi bir araç kullanıyorsan bu planı ona verip ilgili dosyalarda yukarıdaki maddeleri uygulamasını isteyebilirsin; manuel çalışıyorsan aynı adımları sırayla izleyebilirsin.
- Eksik olan dosya yollarını (template ve Python entrypoint) netleştirmeden değişikliğe başlama; doğru dosyayı bulduğunda tema/spacing/typografi adımlarını sırayla uygula.

Bu plan, mevcut HTML yapısını koruyarak görsel dili premium hâle getirmek için uygulanacak değişikliklerin özetidir. Gerekli dosya yolları paylaşıldığında doğrudan düzenleme yapılabilir.

