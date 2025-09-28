# Proteus API Integration for Home Assistant

Integrace pro Home Assistant umožňující ovládání a monitorování fotovoltaické soustavy přes Proteus API od Delta Green.

## Funkce

- **Sensory** - sledování stavu flexibility, zisku z flexibility, předpovědí výroby a spotřeby
- **Binární sensory** - sledování stavu manuálních ovládání
- **Přepínače** - ovládání manuálních funkcí a automatického režimu
- **Automatická aktualizace** - data se aktualizují každých 30 sekund

## Instalace

### Přes HACS (doporučeno)

1. Otevřete HACS v Home Assistant
2. V HACS tři tečky -> vlastní repozitáře -> zkopírovat URL adresu repozitáře na github: **https://github.com/Busak007/proteus-api-ha**
Zvolit že to je **integrace** a **Přidat**
3. Přejděte na **Integrations**
4. Klikněte na **Explore & Download Repositories**
5. Vyhledejte "Proteus API"
6. Klikněte na **Download**
7. Restartujte Home Assistant

### Manuální instalace

1. Stáhněte nebo naklonujte tento repozitář
2. Zkopírujte složku `custom_components/proteus_api` do `config/custom_components/proteus_api`
3. Restartujte Home Assistant

## Konfigurace

1. Přejděte na **Nastavení** → **Zařízení a služby**
2. Klikněte na **Přidat integraci**
3. Vyhledejte "Proteus API"
4. Zadejte požadované údaje:
   - **ID invertoru**: Najdete v URL na stránce invertoru (https://proteus.deltagreen.cz/cs/device/inverter/XXX)
   - **Session cookie**: Zkopírujte z vývojářských nástrojů prohlížeče (F12)

### Získání session cookie

1. Přihlaste se na https://proteus.deltagreen.cz
2. Otevřete vývojářské nástroje (F12)
3. Přejděte na záložku **Application** (Chrome) nebo **Storage** (Firefox)
4. V sekci **Cookies** najděte `proteus_session`
5. Zkopírujte hodnotu cookie

## Dostupné entity

### Sensory

- `sensor.proteus_flexibilita_dostupna` - Stav dostupnosti flexibility
- `sensor.proteus_rezim` - Aktuální režim (AUTOMATIC/MANUAL)
- `sensor.proteus_obchodovani_flexibility_dnes` - Dnešní zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_za_mesic` - Měsíční zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_celkem` - Celkový zisk z flexibility
- `sensor.proteus_prikaz_flexibility` - Aktuální příkaz flexibility
- `sensor.proteus_konec_flexibility` - Konec příkazu flexibility
- `sensor.proteus_rezim_baterie` - Režim baterie
- `sensor.proteus_zalozhni_rezim_baterie` - Záložní režim baterie
- `sensor.proteus_rezim_vyroby` - Režim výroby
- `sensor.proteus_cilovy_soc` - Cílový SOC baterie
- `sensor.proteus_odhad_vyroby` - Předpovězená výroba
- `sensor.proteus_odhad_spotreby` - Předpovězená spotřeba

### Binární sensory

- `binary_sensor.proteus_prodej_do_site_misto_nabijeni` - Prodej do sítě místo nabíjení
- `binary_sensor.proteus_prodej_z_baterie_do_site` - Prodej z baterie do sítě
- `binary_sensor.proteus_setreni_energie_v_baterii` - Šetření energie v baterii
- `binary_sensor.proteus_nabijeni_baterie_ze_site` - Nabíjení baterie ze sítě
- `binary_sensor.proteus_zakaz_pretoku` - Zákaz přetoků

### Přepínače

- `switch.proteus_prodej_do_site_misto_nabijeni` - Ovládání prodeje do sítě místo nabíjení
- `switch.proteus_prodej_z_baterie_do_site` - Ovládání prodeje z baterie do sítě
- `switch.proteus_setreni_energie_v_baterii` - Ovládání šetření energie v baterii
- `switch.proteus_nabijeni_baterie_ze_site` - Ovládání nabíjení baterie ze sítě
- `switch.proteus_zakaz_pretoku` - Ovládání zákazu přetoků
- `switch.proteus_optimalizace_algoritmem` - Přepínání mezi automatickým a manuálním režimem

## Známé problémy

- Občas může aktualizace selhat s chybou TLS/SSL connection has been closed (EOF)
- V takovém případě se sensory stanou na 30 sekund nedostupné
- Session cookie je potřeba obnovit přibližně jednou za měsíc

## Licence

MIT License

## Podpora

Pro hlášení chyb nebo návrhy vylepšení použijte GitHub Issues.
