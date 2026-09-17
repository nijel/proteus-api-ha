# Proteus API Integration for Home Assistant

[![🔌 Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nijel&repository=proteus-api-ha&category=integration)

Integrace pro Home Assistant umožňující ovládání a monitorování fotovoltaické soustavy přes Proteus API od Delta Green.

## Varování

- Používá nestabilní a nedokumentované API, takže se při změnách může rozbít.
- Stav se načítá jednou za 10 sekund.

## Funkce

- **Sensory** - sledování stavu flexibility, zisku z flexibility, předpovědí výroby a spotřeby
- **Binární sensory** - sledování stavu manuálních ovládání
- **Přepínače** - ovládání manuálních funkcí a automatického režimu
- **Automatická aktualizace** - data se aktualizují každých 10 sekund

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
   - **E-mail a heslo**: V Proteovi musí být nastavené přihlašování heslem (ne proklikem z https://moje.deltagreen.cz/, ale vytvořením přihlašovacích údajů na https://proteus.deltagreen.cz/)

Integrace automaticky objeví všechny invertory dostupné ve vašem účtu a vytvoří entity pro každý z nich.

## Dostupné entity

### Sensory

- `sensor.proteus_flexibilita_dostupna` - Stav dostupnosti flexibility (USABLE/NOT_USABLE)
- `sensor.proteus_rezim` - Aktuální režim (AUTOMATIC/MANUAL)
- `sensor.proteus_rezim_flexibility` - Režim flexibility (FULL/NONE)
- `sensor.proteus_obchodovani_flexibility_dnes` - Dnešní zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_za_mesic` - Měsíční zisk z flexibility
- `sensor.proteus_obchodovani_flexibility_celkem` - Celkový zisk z flexibility
- `sensor.proteus_prikaz_flexibility` - Aktuální příkaz flexibility
  - atributy: `command_id`, `command_source`, `command_start`, `command_effective_end`, `command_is_testing`, `flexibility_price_kwh`, `price_up_kwh`, `price_down_kwh`
  - `UP_POWER` - Dodávka do sítě
  - `DOWN_BATTERY_SOLAR_CURTAILMENT_POWER` - Odběr ze sítě
  - `DOWN_SOLAR_CURTAILMENT_POWER` - Zákaz přetoků
  - `BALANCING_SERVICES` - Výkonová rovnováha
  - `NONE` - Žádný
- `sensor.proteus_cena_flexibility` - Aktuální cena flexibility v Kč/kWh
  - atributy: `flexibility_price_mwh`, `price_up_kwh`, `price_down_kwh`
- `sensor.proteus_konec_flexibility` - Konec příkazu flexibility
- `sensor.proteus_rezim_baterie` - Režim baterie
- `sensor.proteus_zalozhni_rezim_baterie` - Záložní režim baterie
- `sensor.proteus_rezim_vyroby` - Režim výroby
- `sensor.proteus_cilovy_soc` - Cílový SOC baterie
- `sensor.proteus_odhad_vyroby` - Předpovězená výroba
- `sensor.proteus_odhad_spotreby` - Předpovězená spotřeba
- `sensor.proteus_cena_spotreby` - Aktuální cena spotřeby v Kč/kWh
  - atributy: `price_consumption_mwh`, `price_mwh`, `distribution_price`, `distribution_tariff_type`, `fee_electricity_buy`, `fee_electricity_sell`, `tax_electricity`, `system_services`, `poze`, `vat_rate`, `price_list` (kompletní ceník spotřeby na aktuální a další den, pole objektů `{start, price_kwh}`)
- `sensor.proteus_cena_vyroby` - Aktuální cena výroby v Kč/kWh
  - atributy: `price_production_mwh`, `price_list` (kompletní ceník výroby na aktuální a další den, pole objektů `{start, price_kwh}`)
- `sensor.proteus_distribucni_tarif` - Aktuální distribuční tarif (`HT` = High tariff, `LT` = Low tariff)
- `sensor.proteus_plan_rizeni` - Počet kroků v aktivním plánu řízení
  - atributy: `steps` (celý plán řízení - pole kroků s `start`, `duration_minutes`, `flexalgo_battery`, `flexalgo_pv`, `target_soc`, `is_prediction`, `price_consumption_kwh`, `price_production_kwh`, `distribution_tariff_type`), `plan_id`, `plan_created_at`

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

## Služby

### `proteus_api.set_predictions`

Přepíše předpověď spotřeby a/nebo výroby, se kterou plánuje optimalizační algoritmus Protea (stejná funkce jako ruční úprava v Proteovi na stránce plánu). Užitečné, když má člověk vlastní, přesnější předpověď (např. Solcast) nebo ví o něčem, co Proteus vědět nemůže.

Cíl služby je zařízení (invertor); bez cíle se předpověď zapíše všem nakonfigurovaným invertorům.

Pole `predictions` je seznam hodinových hodnot, každá položka obsahuje:

- `time` - začátek hodiny (naivní čas se bere v časové zóně Home Assistantu)
- `consumption_kwh` - předpokládaná spotřeba za tu hodinu v kWh (volitelné)
- `production_kwh` - předpokládaná výroba FVE za tu hodinu v kWh (volitelné)

Aspoň jedna z hodnot musí být uvedená. Vynechaná veličina zůstane na předpovědi Protea, takže jde přepsat třeba jen výrobu a spotřebu nechat na Proteovi.

```yaml
action: proteus_api.set_predictions
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  predictions:
    - time: "2026-08-09T19:00:00"
      consumption_kwh: 0.7
      production_kwh: 0.3
    - time: "2026-08-09T20:00:00"
      production_kwh: 0.0
```

### `proteus_api.clear_predictions`

Zruší přepsané předpovědi pro dané hodiny; Proteus pak zase plánuje podle svých vlastních (stejné jako tlačítko reset v Proteovi). Cíl služby je stejný jako u `set_predictions`.

Pole `times` je seznam začátků hodin, u kterých se má přepis odstranit.

```yaml
action: proteus_api.clear_predictions
target:
  device_id: 0123456789abcdef0123456789abcdef
data:
  times:
    - "2026-08-09T19:00:00"
    - "2026-08-09T20:00:00"
```

## Vývoj

Projekt používá `uv` a závislosti pro testy jsou definované v `pyproject.toml`.

Instalace vývojového prostředí:

```console
uv sync --group dev
```

Spuštění testů:

```console
uv run --group dev python -m pytest tests -v
```

## Licence

MIT License

## Podpora

Pro hlášení chyb nebo návrhy vylepšení použijte GitHub Issues.
