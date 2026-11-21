"""Country normalisation: ISO-2/ISO-3 codes, names and nationalities -> one canonical name.

Unknown strings return None (unknown stays unknown, so they can never cause a location mismatch).
Territories are their own country. "International" and "Europe" are not countries.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional

# Canonical name | ISO-2 | ISO-3 | other names and nationalities (;-separated)
_TABLE = """
Afghanistan|AF|AFG|afghan
Albania|AL|ALB|albanian
Algeria|DZ|DZA|algerian
American Samoa|AS|ASM|
Andorra|AD|AND|andorran
Angola|AO|AGO|angolan
Anguilla|AI|AIA|anguillan
Antigua and Barbuda|AG|ATG|antigua;antiguan;barbudan
Argentina|AR|ARG|argentine;argentinian;argentinean
Armenia|AM|ARM|armenian
Aruba|AW|ABW|aruban
Australia|AU|AUS|australian
Austria|AT|AUT|austrian
Azerbaijan|AZ|AZE|azerbaijani;azeri
Bahamas|BS|BHS|the bahamas;bahamian
Bahrain|BH|BHR|bahraini
Bangladesh|BD|BGD|bangladeshi
Barbados|BB|BRB|barbadian;bajan
Belarus|BY|BLR|belarusian;byelorussia
Belgium|BE|BEL|belgian
Belize|BZ|BLZ|belizean
Benin|BJ|BEN|beninese
Bermuda|BM|BMU|bermudian
Bhutan|BT|BTN|bhutanese
Bolivia|BO|BOL|bolivian;plurinational state of bolivia;bolivia plurinational state of
Bosnia and Herzegovina|BA|BIH|bosnia;bosnian;herzegovinian;bosnia herzegovina
Botswana|BW|BWA|botswanan;motswana;batswana
Brazil|BR|BRA|brazilian;brasil
British Virgin Islands|VG|VGB|virgin islands british;bvi
Brunei|BN|BRN|bruneian;brunei darussalam
Bulgaria|BG|BGR|bulgarian
Burkina Faso|BF|BFA|burkinabe
Burundi|BI|BDI|burundian
Cambodia|KH|KHM|cambodian;kampuchea
Cameroon|CM|CMR|cameroonian
Canada|CA|CAN|canadian
Cape Verde|CV|CPV|cabo verde;cape verdean
Cayman Islands|KY|CYM|caymanian;cayman
Central African Republic|CF|CAF|central african;car
Chad|TD|TCD|chadian
Chile|CL|CHL|chilean
China|CN|CHN|chinese;peoples republic of china;prc;mainland china
Colombia|CO|COL|colombian
Comoros|KM|COM|comoran;comorian
Congo|CG|COG|republic of the congo;congo brazzaville;congolese republic of the congo;republic of congo
Democratic Republic of the Congo|CD|COD|drc;dr congo;congo kinshasa;democratic republic of congo;congo democratic republic of the;congo the democratic republic of the;zaire
Cook Islands|CK|COK|cook islander
Costa Rica|CR|CRI|costa rican
Cote d'Ivoire|CI|CIV|ivory coast;ivorian;cote divoire
Croatia|HR|HRV|croatian;croat
Cuba|CU|CUB|cuban
Curacao|CW|CUW|curacaoan
Cyprus|CY|CYP|cypriot
Czech Republic|CZ|CZE|czechia;czech
Denmark|DK|DNK|danish;dane
Djibouti|DJ|DJI|djiboutian
Dominica|DM|DMA|dominican dominica
Dominican Republic|DO|DOM|dominican
Ecuador|EC|ECU|ecuadorian;ecuadorean
Egypt|EG|EGY|egyptian
El Salvador|SV|SLV|salvadoran;salvadorean
Equatorial Guinea|GQ|GNQ|equatoguinean;equatorial guinean
Eritrea|ER|ERI|eritrean
Estonia|EE|EST|estonian
Eswatini|SZ|SWZ|swaziland;swazi
Ethiopia|ET|ETH|ethiopian
Falkland Islands|FK|FLK|falklands;falkland islander;malvinas
Faroe Islands|FO|FRO|faroese;faroes
Fiji|FJ|FJI|fijian
Finland|FI|FIN|finnish;finn
France|FR|FRA|french
French Guiana|GF|GUF|
French Polynesia|PF|PYF|
Gabon|GA|GAB|gabonese
Gambia|GM|GMB|the gambia;gambian
Georgia|GE|GEO|georgian
Germany|DE|DEU|german;deutschland;federal republic of germany
Ghana|GH|GHA|ghanaian
Gibraltar|GI|GIB|gibraltarian
Greece|GR|GRC|greek;hellenic republic
Greenland|GL|GRL|greenlandic;greenlander
Grenada|GD|GRD|grenadian
Guadeloupe|GP|GLP|
Guam|GU|GUM|guamanian
Guatemala|GT|GTM|guatemalan
Guernsey|GG|GGY|
Guinea|GN|GIN|guinean
Guinea-Bissau|GW|GNB|bissau guinean;guinea bissau
Guyana|GY|GUY|guyanese
Haiti|HT|HTI|haitian
Honduras|HN|HND|honduran
Hong Kong|HK|HKG|hong konger;hongkonger;hong kong sar;hong kong sar china;hksar
Hungary|HU|HUN|hungarian
Iceland|IS|ISL|icelandic;icelander
India|IN|IND|indian
Indonesia|ID|IDN|indonesian
Iran|IR|IRN|iranian;persia;persian;islamic republic of iran;iran islamic republic of
Iraq|IQ|IRQ|iraqi
Ireland|IE|IRL|irish;republic of ireland;eire
Isle of Man|IM|IMN|manx
Israel|IL|ISR|israeli
Italy|IT|ITA|italian
Jamaica|JM|JAM|jamaican
Japan|JP|JPN|japanese
Jersey|JE|JEY|
Jordan|JO|JOR|jordanian
Kazakhstan|KZ|KAZ|kazakh;kazakhstani
Kenya|KE|KEN|kenyan
Kiribati|KI|KIR|i kiribati
Kosovo|XK|XKX|kosovar;kosovan
Kuwait|KW|KWT|kuwaiti
Kyrgyzstan|KG|KGZ|kyrgyz;kirghiz;kyrgyz republic
Laos|LA|LAO|lao;laotian;lao peoples democratic republic
Latvia|LV|LVA|latvian
Lebanon|LB|LBN|lebanese
Lesotho|LS|LSO|basotho;mosotho
Liberia|LR|LBR|liberian
Libya|LY|LBY|libyan;libyan arab jamahiriya
Liechtenstein|LI|LIE|liechtensteiner
Lithuania|LT|LTU|lithuanian
Luxembourg|LU|LUX|luxembourgish;luxembourger
Macau|MO|MAC|macao;macanese;macao sar;macau sar
Madagascar|MG|MDG|malagasy
Malawi|MW|MWI|malawian
Malaysia|MY|MYS|malaysian
Maldives|MV|MDV|maldivian
Mali|ML|MLI|malian
Malta|MT|MLT|maltese
Marshall Islands|MH|MHL|marshallese
Martinique|MQ|MTQ|
Mauritania|MR|MRT|mauritanian
Mauritius|MU|MUS|mauritian
Mayotte|YT|MYT|
Mexico|MX|MEX|mexican
Micronesia|FM|FSM|micronesian;federated states of micronesia
Moldova|MD|MDA|moldovan;republic of moldova;moldova republic of
Monaco|MC|MCO|monegasque;monacan
Mongolia|MN|MNG|mongolian
Montenegro|ME|MNE|montenegrin
Montserrat|MS|MSR|montserratian
Morocco|MA|MAR|moroccan
Mozambique|MZ|MOZ|mozambican
Myanmar|MM|MMR|burma;burmese
Namibia|NA|NAM|namibian
Nauru|NR|NRU|nauruan
Nepal|NP|NPL|nepalese;nepali
Netherlands|NL|NLD|dutch;holland;the netherlands;kingdom of the netherlands
New Caledonia|NC|NCL|
New Zealand|NZ|NZL|new zealander;kiwi
Nicaragua|NI|NIC|nicaraguan
Niger|NE|NER|nigerien
Nigeria|NG|NGA|nigerian
North Korea|KP|PRK|dprk;democratic peoples republic of korea;korea democratic peoples republic of;north korean;korea north
North Macedonia|MK|MKD|macedonia;macedonian;republic of north macedonia;fyrom
Norway|NO|NOR|norwegian
Oman|OM|OMN|omani
Pakistan|PK|PAK|pakistani
Palau|PW|PLW|palauan
Palestine|PS|PSE|palestinian;state of palestine;palestinian territories;occupied palestinian territory;west bank;gaza;gaza strip
Panama|PA|PAN|panamanian
Papua New Guinea|PG|PNG|papua new guinean;papuan
Paraguay|PY|PRY|paraguayan
Peru|PE|PER|peruvian
Philippines|PH|PHL|filipino;filipina;philippine;the philippines
Poland|PL|POL|polish;pole
Portugal|PT|PRT|portuguese
Puerto Rico|PR|PRI|puerto rican
Qatar|QA|QAT|qatari
Reunion|RE|REU|
Romania|RO|ROU|romanian;rumania
Russia|RU|RUS|russian;russian federation
Rwanda|RW|RWA|rwandan
Saint Kitts and Nevis|KN|KNA|st kitts and nevis;kittitian;nevisian;st kitts
Saint Lucia|LC|LCA|st lucia;saint lucian;st lucian
Saint Vincent and the Grenadines|VC|VCT|st vincent and the grenadines;vincentian;st vincent
Samoa|WS|WSM|samoan
San Marino|SM|SMR|sammarinese
Sao Tome and Principe|ST|STP|sao tomean
Saudi Arabia|SA|SAU|saudi;saudi arabian;ksa
Senegal|SN|SEN|senegalese
Serbia|RS|SRB|serbian;serb
Seychelles|SC|SYC|seychellois
Sierra Leone|SL|SLE|sierra leonean
Singapore|SG|SGP|singaporean
Sint Maarten|SX|SXM|
Slovakia|SK|SVK|slovak;slovak republic
Slovenia|SI|SVN|slovenian;slovene
Solomon Islands|SB|SLB|solomon islander
Somalia|SO|SOM|somali
South Africa|ZA|ZAF|south african;rsa
South Korea|KR|KOR|korea;republic of korea;korea republic of;south korean;korean;korea south
South Sudan|SS|SSD|south sudanese
Spain|ES|ESP|spanish;espana
Sri Lanka|LK|LKA|sri lankan;ceylon
Sudan|SD|SDN|sudanese
Suriname|SR|SUR|surinamese;surinam
Sweden|SE|SWE|swedish;swede
Switzerland|CH|CHE|swiss
Syria|SY|SYR|syrian;syrian arab republic
Taiwan|TW|TWN|taiwanese;republic of china;taiwan province of china
Tajikistan|TJ|TJK|tajik;tajikistani
Tanzania|TZ|TZA|tanzanian;united republic of tanzania;tanzania united republic of
Thailand|TH|THA|thai
Timor-Leste|TL|TLS|east timor;timorese;timor leste
Togo|TG|TGO|togolese
Tonga|TO|TON|tongan
Trinidad and Tobago|TT|TTO|trinidadian;tobagonian;trinidad
Tunisia|TN|TUN|tunisian
Turkey|TR|TUR|turkish;turkiye
Turkmenistan|TM|TKM|turkmen
Turks and Caicos Islands|TC|TCA|turks and caicos
Tuvalu|TV|TUV|tuvaluan
Uganda|UG|UGA|ugandan
Ukraine|UA|UKR|ukrainian
United Arab Emirates|AE|ARE|uae;emirati;emirates
United Kingdom|GB|GBR|uk;united kingdom of great britain and northern ireland;great britain;britain;british;england;english;scotland;scottish;wales;welsh;northern ireland;northern irish
United States|US|USA|united states of america;america;american;us citizen
US Virgin Islands|VI|VIR|virgin islands us;united states virgin islands
Uruguay|UY|URY|uruguayan
Uzbekistan|UZ|UZB|uzbek;uzbekistani
Vanuatu|VU|VUT|ni vanuatu
Vatican City|VA|VAT|holy see;vatican
Venezuela|VE|VEN|venezuelan;bolivarian republic of venezuela;venezuela bolivarian republic of
Vietnam|VN|VNM|vietnamese;viet nam
Western Sahara|EH|ESH|sahrawi
Yemen|YE|YEM|yemeni
Zambia|ZM|ZMB|zambian
Zimbabwe|ZW|ZWE|zimbabwean
"""

NOT_COUNTRIES = {"international", "europe", "global", "worldwide", "unknown", "none", "na", "n a", "other"}


def _key(s) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"['’`.]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    return s.replace(" and ", " ").replace(" & ", " ")


_LOOKUP: Dict[str, str] = {}
for _line in _TABLE.strip().splitlines():
    _name, _a2, _a3, _alts = _line.split("|")
    for _k in [_name, _a2, _a3] + [a for a in _alts.split(";") if a]:
        _LOOKUP.setdefault(_key(_k), _name)
_LOOKUP.setdefault("uk", "United Kingdom")   # not ISO, but common


def normalise(s) -> Optional[str]:
    """Canonical country name, or None if it is not a recognised country."""
    if s is None:
        return None
    k = _key(s)
    if not k or k in NOT_COUNTRIES:
        return None
    return _LOOKUP.get(k)


def from_address(addr) -> Optional[str]:
    """Country of an address = its last comma-separated part (postcode digits ignored)."""
    if not addr:
        return None
    last = str(addr).split(",")[-1]
    return normalise(last) or normalise(re.sub(r"\d+", " ", last))
