# Proteus API Integration for Home Assistant

[![🔌 Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nijel&repository=proteus-api-ha&category=integration)

Integrace pro Home Assistant umožňující ovládání a monitorování fotovoltaické soustavy přes Proteus API od Delta Green.

## Varování

- Používá nestabilní a nedokumentované API, takže se při změnách může rozbít.
- Stav se načítá jednou za 30 sekund.

## Funkce

- **Sensory** - sledování stavu flexibility, zisku z flexibility, předpovědí výroby a spotřeby
- **Binární sensory** - sledování stavu manuálních ovládání
- **Přepínače** - ovládání manuálních funkcí a automatického režimu
- **Automatická aktualizace** - data se aktualizují každých 30 sekund

## Instalace

### Přes HACS (doporučeno)

1. Otevřete HACS v Home Assistant
1. V HACS tři tečky -> vlastní repozitáře -> zkopírovat URL adresu repozitáře na github: **https://github.com/nijel/proteus-api-ha**. Zvolit že to je **integrace** a **Přidat**.
1. Přejděte na **Integrations**
1. Klikněte na **Explore & Download Repositories**
1. Vyhledejte "Proteus API"
1. Klikněte na **Download**
1. Restartujte Home Assistant

### Manuální instalace

1. Stáhněte nebo naklonujte tento repozitář
1. Zkopírujte složku `custom_components/proteus_api` do `config/custom_components/proteus_api`
1. Restartujte Home Assistant

## Konfigurace

1. Přejděte na **Nastavení** → **Zařízení a služby**
1. Klikněte na **Přidat integraci**
1. Vyhledejte "Proteus API"
1. Zadejte požadované údaje:
   - **ID invertoru**: Najdete v URL na stránce invertoru (https://proteus.deltagreen.cz/cs/device/inverter/XXX)
   - **Uživatelské jméno a heslo**: V Proteovi musí být nastavené přihlašování heslem (ne proklikem z https://moje.deltagreen.cz/, ale vytvořením přihlašovacích údajů na https://proteus.deltagreen.cz/)

## Dostupné entity

### Sensory

- `sensor.proteus_flexibilita_dostupna` - Stav dostupnosti flexibility (USABLE/NOT_USABLE)
- `sensor.proteus_rezim` - Aktuální režim (AUTOMATIC/MANUAL)
- `sensor.proteus_rezim_flexibility` - Režim flexibility (FULL/NONE)
- `sensor.proteus_obchodovani_flexibility_dnes` - Dnešní zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_za_mesic` - Měsíční zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_celkem` - Celkový zisk z flexibility
- `sensor.proteus_prikaz_flexibility` - Aktuální příkaz flexibility
  - `UP_POWER` - Dodávka do sítě
  - `DOWN_BATTERY_SOLAR_CURTAILMENT_POWER` - Odběr ze sítě
  - `DOWN_SOLAR_CURTAILMENT_POWER` - Zákaz přetoků
  - `NONE` - Žádný
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

- `switch.proteus_obchodovani_flexiblity` - Přepínání obchodování flexibility
- `switch.proteus_optimalizace_algoritmem` - Přepínání mezi automatickým a manuálním režimem
- `switch.proteus_prodej_do_site_misto_nabijeni` - Ovládání prodeje do sítě místo nabíjení
- `switch.proteus_prodej_z_baterie_do_site` - Ovládání prodeje z baterie do sítě
- `switch.proteus_setreni_energie_v_baterii` - Ovládání šetření energie v baterii
- `switch.proteus_nabijeni_baterie_ze_site` - Ovládání nabíjení baterie ze sítě
- `switch.proteus_zakaz_pretoku` - Ovládání zákazu přetoků
- `switch.proteus_rizeni_fve` - Povolení řízení FVE

## Licence

MIT License

## Podpora

Pro hlášení chyb nebo návrhy vylepšení použijte GitHub Issues.
