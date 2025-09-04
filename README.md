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
2. Přejděte na **Integrations**
3. Klikněte na **Explore & Download Repositories**
4. Vyhledejte "Proteus API"
5. Klikněte na **Download**
6. Restartujte Home Assistant

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
   - **Uživatelské jméno a heslo**: V Proteovi musí být nastavené přihlašování heslem

## Dostupné entity

### Sensory

- `sensor.proteus_flexibilita_dostupna` - Stav dostupnosti flexibility (USABLE/NOT_USABLE)
- `sensor.proteus_rezim` - Aktuální režim (AUTOMATIC/MANUAL)
- `sensor.proteus_rezim_flexibility` - Režim flexibility (FULL/NONE)
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

- `switch.proteus_obchodovani_flexiblity` - Přepínání obchodování flexibility
- `switch.proteus_optimalizace_algoritmem` - Přepínání mezi automatickým a manuálním režimem
- `switch.proteus_prodej_do_site_misto_nabijeni` - Ovládání prodeje do sítě místo nabíjení
- `switch.proteus_prodej_z_baterie_do_site` - Ovládání prodeje z baterie do sítě
- `switch.proteus_setreni_energie_v_baterii` - Ovládání šetření energie v baterii
- `switch.proteus_nabijeni_baterie_ze_site` - Ovládání nabíjení baterie ze sítě
- `switch.proteus_zakaz_pretoku` - Ovládání zákazu přetoků

## Licence

MIT License

## Podpora

Pro hlášení chyb nebo návrhy vylepšení použijte GitHub Issues.
