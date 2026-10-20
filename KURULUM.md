# Deprem X Otomasyonu: Kurulum

Bu klasör iki işi kendi kendine yapar:

1. **Planlı post.** `taslaklar.json` dosyasındaki taslakları sırayla paylaşır. Günde 2 kez çalışır, sabah 09:10–09:55 ve akşam 19:40–20:25 arasında rastgele bir saatte (TSİ).
2. **Deprem bilgisi.** 5 dakikada bir AFAD'a bakar ve Türkiye'deki her yeni M≥4,0 depremi paylaşır. AFAD'a ulaşılamazsa Kandilli'ye, o da olmazsa EMSC'ye bakar.

Çalışmak için bilgisayarınızın açık olması gerekmez. Her şey GitHub'ın sunucularında çalışır.

---

## 1. X geliştirici hesabı (yaklaşık 10 dakika)

1. Tarayıcıda **bot hesabıyla** X'e giriş yapın ve <https://developer.x.com> adresine gidin.
2. Yeni bir uygulama (App) oluşturun. Ad olarak örneğin `deprem-bilgi-bot` yazabilirsiniz.
3. Uygulamada **User authentication settings** bölümünü açın:
   - App permissions: **Read and write**
   - Type of App: **Web App, Automated App or Bot**
   - Callback URI ve Website URL: `https://apps.apple.com/tr/app/id6821462060`
4. **Keys and tokens** sekmesinde dört değer alın:
   - API Key → `X_API_KEY`
   - API Key Secret → `X_API_SECRET`
   - Access Token → `X_ACCESS_TOKEN`
   - Access Token Secret → `X_ACCESS_SECRET`

   Access Token'ı 3. adımdan **sonra** oluşturun. Önceden oluşturduysanız yeniden oluşturun, yoksa yalnızca okuma izni olur.
5. **Billing** bölümünden kredi yükleyin. 5–10 $ birkaç ay yeter. Otomatik yüklemeyi kapalı bırakın.

**Maliyet (X'in Ekim 2026 fiyatları):**

| Ne | Fiyat | Ayda |
|---|---|---|
| Bağlantısız post | 0,015 $ | ~60 planlı post + ~10–30 deprem postu ≈ 1,4 $ |
| Bağlantılı post | 0,20 $ | 66 taslağın 7'sinde bağlantı var ≈ 0,7 $ |

Toplam aylık maliyet yaklaşık **2–3 $**. Bot ayda 8 $'ı geçmez. Bu sınırı aşağıdaki `MONTHLY_BUDGET_USD` ayarıyla değiştirebilirsiniz.

## 2. X hesap ayarları (önemli)

- **Biyografiye App Store bağlantısını ekleyin:** `https://apps.apple.com/tr/app/id6821462060?ct=x_bio`
  Deprem postları bağlantı yerine "profildeki bağlantı" der, çünkü bağlantılı post 13 kat pahalı.
- **"Otomatik hesap" etiketini açın:** Ayarlar → Hesabınız → Hesap bilgileri → Otomasyon → yöneten hesap olarak kendi kişisel hesabınızı seçin.
  X, otomatik paylaşım yapan hesaplardan bu etiketi bekliyor. Etiket hesabı kapatılmaya karşı korur.

## 3. GitHub deposu

1. <https://github.com/new> adresinde yeni bir depo açın. Adı `deprem-x-bot` olabilir.
   - **Public (herkese açık)** seçin. Herkese açık depolarda GitHub Actions ücretsizdir. Özel depoda 5 dakikalık deprem kontrolü ücretsiz kotayı aşar.
   - Depoda yalnızca taslaklar ve kod durur. X anahtarları gizli (Secrets) bölümde saklanır, kimse göremez.
2. Bu klasörü depoya yükleyin. Terminalde:

```bash
cd "/Users/macbook/Desktop/Depre-Anında Bilgi ve İletişim/x-otomasyon" && git init -b main && git add . && git commit -m "Deprem X otomasyonu" && git remote add origin https://github.com/KULLANICI_ADINIZ/deprem-x-bot.git && git push -u origin main
```

   `KULLANICI_ADINIZ` yerine GitHub kullanıcı adınızı yazın.

3. Depoda **Settings → Secrets and variables → Actions → New repository secret** ile dört gizli değeri ekleyin: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.
4. Aynı sayfada **Settings → Actions → General → Workflow permissions** bölümünde **Read and write permissions** seçili olsun. Bot, neyi paylaştığını depoya böyle kaydeder.

## 4. Deneme ve başlatma

1. Depoda **Actions** sekmesine girin. Gerekirse iş akışlarını etkinleştirin.
2. **Planlı post → Run workflow** seçin. "Deneme modu" işaretli kalsın. Çalıştırın.
   Kayıtta paylaşılacak metni görürsünüz. X'e hiçbir şey gitmez.
3. Aynısını **Deprem takip** için yapın.
4. İkisi de sorunsuzsa **Planlı post**'u bu kez "Deneme modu" işaretini kaldırarak çalıştırın. İlk post X'te görünmeli.

Bundan sonra her şey kendiliğinden çalışır.

---

## Bot ne zaman sessiz kalır?

| Durum | Davranış |
|---|---|
| Son 24 saatte M≥5,5 deprem | Uygulama tanıtımı yapılmaz, bağlantı paylaşılmaz. Sırada yalnızca bilgi ve hazırlık postları gider. |
| Son 24 saatte M≥6,5 deprem | Planlı postlar tamamen durur. Yalnızca resmi deprem bilgisi paylaşılır. |
| 1 saatte 4'ten fazla deprem (artçılar) | M<5 olanlar atlanır, M≥5 her zaman paylaşılır. |
| İki planlı post arası 6 saatten azsa | Atlanır. Aynı gün iki kez elle çalıştırmaya karşı korur. |
| Aylık bütçe doldu | Hiçbir şey gönderilmez. |
| Taslak kalmadı | İş "başarısız" olur ve GitHub size e-posta atar. |

Deprem postlarında:
- Uygulama hatırlatması yalnızca her 5. küçük depremde bir satır olarak çıkar.
- M≥5 depremlerde hiç tanıtım yoktur. Bunun yerine güvenlik hatırlatmaları (çök-kapan-tutun, asansör, 112) eklenir.

## Taslak ekleme

`taslaklar.json` dosyasını GitHub'da açın, kalem simgesine tıklayın ve listenin sonuna yeni satırlar ekleyin:

```json
{"id": "h21", "tur": "hazirlik", "metin": "Metin buraya.\n\n#depremhazırlık"},
{"id": "u19", "tur": "uygulama", "baglanti": true, "metin": "Uygulama postu.\n\n#deprem"}
```

Alanlar:
- `id`: Her taslakta farklı olmalı. Paylaşılan taslaklar bu kimlikle hatırlanır.
- `tur`:
  - `uygulama`: tanıtım postu, büyük depremden sonra 24 saat bekletilir.
  - `hazirlik`, `bilgi`, `aile`: her zaman paylaşılabilir.
- `baglanti`: `true` yazarsanız App Store bağlantısı postun sonuna eklenir. Bu post 0,20 $ tutar.
- `\n` yeni satır demektir.

Eklemeden önce bilgisayarda kontrol edebilirsiniz. Bu komut uzunluğu (280), yasaklı kelimeleri ve hashtag sayısını denetler:

```bash
cd "/Users/macbook/Desktop/Depre-Anında Bilgi ve İletişim/x-otomasyon" && python3 bot.py denetle
```

Sıradaki 5 postu ve bu ayki harcamayı görmek için:

```bash
cd "/Users/macbook/Desktop/Depre-Anında Bilgi ve İletişim/x-otomasyon" && python3 bot.py onizle
```

## Ayarlar (isteğe bağlı)

Depoda **Settings → Secrets and variables → Actions → Variables** bölümüne ekleyebilirsiniz:

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `MONTHLY_BUDGET_USD` | 8 | Aylık harcama üst sınırı ($) |
| `MIN_MAGNITUDE` | 4.0 | Bu büyüklüğün altındaki depremler paylaşılmaz |

Paylaşım saatlerini değiştirmek için `.github/workflows/planli-post.yml` içindeki `cron` satırlarını düzenleyin. Saatler UTC'dir: TSİ'den 3 saat çıkarın.

## Bilinmesi gerekenler

- GitHub zamanlanmış işleri yoğun saatlerde 5–20 dakika geciktirebilir. Bot, 45 dakikadan eski depremleri paylaşmaz. Bu yüzden nadiren bir deprem atlanabilir.
- AFAD bir depremin büyüklüğünü sonradan güncelleyebilir. Bot ilk açıklanan değeri paylaşır.
- Bağımlılık yoktur. Yalnızca Python'un kendi kütüphanesi kullanılır.
- Paylaşılan her şey `durum/` klasörüne kaydedilir. Bu dosyaları silerseniz bot taslakları baştan paylaşmaya çalışır. X aynı metni ikinci kez kabul etmez.

## Kontrol paneli

`Deprem X Paneli.command` dosyasına çift tıklayın. Tarayıcıda http://127.0.0.1:8765 açılır. Panel yalnızca bu bilgisayardan erişilebilir.

Panelde yapabilecekleriniz:
- Harcamayı, sıradaki postu ve son çalışmaları görmek
- Bir taslağı ya da sıradakini hemen paylaşmak
- Deneme çalıştırması yapmak
- Taslak eklemek, düzenlemek, silmek ve sırasını değiştirmek
- Otomatik paylaşımı duraklatmak
- Bütçeyi ve en küçük deprem büyüklüğünü değiştirmek

Paneli kapatmak için açılan Terminal penceresini kapatın. Panel kapalıyken de bot GitHub'da çalışmaya devam eder.
