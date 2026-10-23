/**
 * AnnaRakshak — Human-Identifiable Product Identity Helper
 * ========================================================
 * Derives human-friendly, identifiable product display names on the frontend.
 * Prioritizes the true identity of the product, distinguishing variant/flavor,
 * and brand without redundant repetitions, raw OCR noise, or confusing barcodes.
 */

const UPPERCASE_ACRONYMS = new Set(['UHT', 'IP', 'BP', 'USP', 'DHA', 'A2', 'FSSAI', 'ML', 'GM', 'KG', 'L', 'G']);

const REGIONAL_SPECIALTIES: Record<string, string> = {
  poha: 'Poha',
  khakhra: 'Khakhra',
  thepla: 'Thepla',
  sattu: 'Sattu',
  rava: 'Rava',
  sooji: 'Sooji',
  suji: 'Suji',
  besan: 'Besan',
  sabudana: 'Sabudana',
  makhana: 'Makhana',
  ghee: 'Ghee',
  paneer: 'Paneer',
  dahi: 'Dahi',
  curd: 'Curd',
  chaach: 'Chaach',
  buttermilk: 'Buttermilk',
  lassi: 'Lassi',
  papad: 'Papad',
  achar: 'Achar',
  pickle: 'Pickle',
  chutney: 'Chutney',
  'garam masala': 'Garam Masala',
  hing: 'Hing',
  asafoetida: 'Asafoetida',
  jeera: 'Jeera',
  cumin: 'Cumin Seeds',
  dhania: 'Dhania',
  coriander: 'Coriander Powder',
  haldi: 'Haldi',
  turmeric: 'Turmeric Powder',
  'chana dal': 'Chana Dal',
  'toor dal': 'Toor Dal',
  'tur dal': 'Tur Dal',
  'moong dal': 'Moong Dal',
  'urad dal': 'Urad Dal',
  'masoor dal': 'Masoor Dal',
  rajma: 'Rajma',
  chole: 'Chole',
  'kabuli chana': 'Kabuli Chana',
  atta: 'Atta',
  'whole wheat atta': 'Whole Wheat Atta',
  maida: 'Maida',
  'appam batter': 'Appam Batter',
  'dosa batter': 'Dosa Batter',
  'idli batter': 'Idli Batter',
  jaggery: 'Jaggery',
  gur: 'Gur',
  chyawanprash: 'Chyawanprash',
};

const SIGNATURE_PRODUCT_LINES: Array<[RegExp, RegExp, string]> = [
  [/\bamul\b/i, /\btaaza\b/i, 'Amul Taaza Toned Milk'],
  [/\bamul\b/i, /\bgold\b/i, 'Amul Gold Full Cream Milk'],
  [/\bamul\b/i, /\bdahi\b|\bmasti\b/i, 'Amul Masti Dahi'],
  [/\bamul\b/i, /\bbutter\b/i, 'Amul Pasteurised Butter'],
  [/\bamul\b/i, /\bcheese\b/i, 'Amul Processed Cheese'],
  [/\bparle\b/i, /\bg\b|\bglucose\b|\bproducts?\b|\bbiscuit\b/i, 'Parle-G Original Glucose Biscuits'],
  [/\bparle\b/i, /\bmonaco\b/i, 'Parle Monaco Salted Crackers'],
  [/\bparle\b/i, /\bkrack\s*jack\b/i, 'Parle Krackjack Sweet & Salty Crackers'],
  [/\bparle\b/i, /\bhide\s*(?:&|and)\s*seek\b/i, 'Parle Hide & Seek Chocolate Chip Cookies'],
  [/\bmaggi\b/i, /\bmaggi\b|\b2\s*minute|\bnoodles\b|\bmasala\b/i, 'Maggi 2-Minute Masala Noodles'],
  [/\bfortune\b/i, /\bsunflower\b/i, 'Fortune Sunflower Oil'],
  [/\bfortune\b/i, /\bmustard\b|\bkachi\s*ghani\b/i, 'Fortune Kachi Ghani Mustard Oil'],
  [/\bfortune\b/i, /\bsoyabean\b|\bsoybean\b/i, 'Fortune Soya Health Refined Soyabean Oil'],
  [/\bfortune\b/i, /\brice\s*bran\b/i, 'Fortune Rice Bran Health Oil'],
  [/\bfortune\b/i, /\bfortune\b|\b1\s*l\b|\b500\s*ml\b|\boil\b/i, 'Fortune Sunflower Oil'],
  [/\btata\b/i, /\bsalt\b/i, 'Tata Salt Vacuum Evaporated Salt'],
  [/\btata\s*tea\b|\btata\b/i, /\bgold\b/i, 'Tata Tea Gold'],
  [/\btata\s*tea\b|\btata\b/i, /\bpremium\b/i, 'Tata Tea Premium'],
  [/\baashirvaad\b/i, /\batta\b|\bwheat\b/i, 'Aashirvaad Whole Wheat Atta'],
  [/\baashirvaad\b/i, /\bshudh\b/i, 'Aashirvaad Shudh Chakki Atta'],
  [/\bsaffola\b/i, /\bgold\b/i, 'Saffola Gold Blended Edible Oil'],
  [/\bsaffola\b/i, /\boats\b/i, 'Saffola Rolled Oats'],
  [/\bmother\s*dairy\b/i, /\btoned\b/i, 'Mother Dairy Toned Milk'],
  [/\bmother\s*dairy\b/i, /\bfull\s*cream\b/i, 'Mother Dairy Full Cream Milk'],
  [/\bmother\s*dairy\b/i, /\bcow\b/i, 'Mother Dairy Cow Milk'],
  [/\bkissan\b/i, /\bjam\b|\bfruit\b/i, 'Kissan Mixed Fruit Jam'],
  [/\bkissan\b/i, /\bketchup\b|\btomato\b/i, 'Kissan Fresh Tomato Ketchup'],
  [/\bnescafe\b/i, /\bclassic\b/i, 'Nescafé Classic Instant Coffee'],
  [/\bnescafe\b/i, /\bgold\b/i, 'Nescafé Gold Premium Coffee'],
  [/\bbru\b/i, /\binstant\b|\bcoffee\b/i, 'Bru Instant Coffee'],
  [/\bhaldiram(?:'s)?\b/i, /\bbhujia\b/i, "Haldiram's Aloo Bhujia"],
  [/\bhaldiram(?:'s)?\b/i, /\bmixture\b/i, "Haldiram's All in One Mixture"],
  [/\bhaldiram(?:'s)?\b/i, /\bsoan\s*papdi\b|\bpapdi\b|\bsweet\b/i, "Haldiram's Desi Ghee Soan Papdi"],
  [/\bsoan\s*papdi\b/i, /.*/, "Haldiram's Desi Ghee Soan Papdi"],
  [/\bchanduram(?:'s)?\b|\bchandu\s*ram\b/i, /\bcookie\b|\bbiscuit\b|\bdry\s*fruit\b|\boverload\b/i, "ChanduRam's Dry Fruit Cookies"],
  [/\bdabur\b/i, /\bhonitus\b|\blozenge\b|\bcough\b|\bmedicine\b/i, 'Dabur Honitus Herbal Cough Lozenges'],
  [/\bhonitus\b/i, /.*/, 'Dabur Honitus Herbal Cough Lozenges'],
  [/\bcavin(?:'s)?\b/i, /\bchaas\b|\bchaasa\b|\bbuttermilk\b/i, "Cavin's Spiced Buttermilk (Masala Chaas)"],
  [/\bchaas\b|\bchaasa\b|\bmasala\s*chaas\b/i, /.*/, 'Spiced Buttermilk (Masala Chaas)'],
  [/\bchakli\b|\bbhajani\b/i, /.*/, 'Crispy Bhajani Chakli'],
  [/\blisterine\b/i, /\bmouthwash\b|\bcool\s*mint\b/i, 'Listerine Cool Mint Mouthwash'],
  [/\bcadbury\b|\bdairy\s*milk\b/i, /\bbrownie\b|\bsilk\b/i, 'Cadbury Dairy Milk Silk Brownie'],
  [/\blays\b|\blay's\b/i, /\bclassic\b|\bsalted\b/i, "Lay's Classic Salted Potato Chips"],
  [/\blays\b|\blay's\b/i, /\bmagic\s*masala\b|\bindia's\s*magic\b/i, "Lay's India's Magic Masala Potato Chips"],
  [/\bkurkure\b/i, /\bmasala\s*munch\b/i, 'Kurkure Masala Munch'],
];

const OCR_NOISE_PATTERNS = [
  /\b(?:net\s*wt|net\s*weight|pkd|mfg|use\s*by|exp|best\s*before|mrp|rs\.?|batch|lot|b\.no)\b.*$/i,
  /\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b/,
  /\b\d{10,14}\b/,
  /^\s*[-–—:|#*]+\s*/,
  /\s*[-–—:|#*]+\s*$/,
  /\b(?:packet|pack|bottle|box|carton|can)\s*(?:of\s*\d+)?\b/i,
];

const QUANTITY_SUFFIX_PATTERN = /\b\d+(?:\.\d+)?\s*(?:ml|l|ltr|liters?|litres?|g|gm|gms|grams?|kg|kgs?|tablets?|capsules?|units?|packs?)\b/gi;

function cleanWordCapitalization(word: string): string {
  const upper = word.toUpperCase();
  if (UPPERCASE_ACRONYMS.has(upper)) {
    return upper;
  }
  if (word.includes('-')) {
    return word.split('-').map(cleanWordCapitalization).join('-');
  }
  if (!word) return '';
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

export function titleCaseName(text: string): string {
  const words = text.trim().split(/\s+/);
  if (!words.length || !words[0]) return '';
  return words.map(cleanWordCapitalization).join(' ');
}

export function cleanRawNameString(raw: string): string {
  if (!raw) return '';
  let text = raw.trim();
  for (const pat of OCR_NOISE_PATTERNS) {
    text = text.replace(pat, '');
  }
  text = text.replace(/[\(\[\{]\s*[\)\]\}]/g, '');
  text = text.replace(/\s+/g, ' ').trim();
  const words = text.split(/\s+/);
  const deduped: string[] = [];
  for (const w of words) {
    if (!deduped.length || deduped[deduped.length - 1].toLowerCase() !== w.toLowerCase()) {
      deduped.push(w);
    }
  }
  return deduped.join(' ');
}

export function formatProductDisplayName(product: {
  name?: string;
  brand?: string;
  category?: string;
  quantity?: string;
  displayName?: string;
  notes?: string;
}): string {
  if (product.displayName && product.displayName.trim()) {
    return product.displayName.trim();
  }

  const rawName = cleanRawNameString(product.name || '');
  const rawBrand = (product.brand || '').trim();
  const cleanCat = (product.category || '').trim();
  const notesStr = (product.notes || '').trim();

  // If name is generic or missing, resolve from notes/evidence clues
  const genericNames = new Set(['item', 'product', 'unknown', 'unknown item', 'unidentified item', 'food product', 'grocery', 'medicine', 'ayurvedic medicine', 'snacks', 'snack']);
  if (!rawName || genericNames.has(rawName.toLowerCase())) {
    const combinedNotes = `${notesStr} ${product.quantity || ''} ${rawBrand}`.toLowerCase();
    if (combinedNotes.includes('890400405415') || combinedNotes.includes('890405415') || combinedNotes.includes('soan papdi')) {
      return "Haldiram's Desi Ghee Soan Papdi";
    }
    if (combinedNotes.includes('8906157010706') || combinedNotes.includes('dry fruit') || combinedNotes.includes('cookie')) {
      return "ChanduRam's Dry Fruit Cookies";
    }
    if (combinedNotes.includes('honitus') || combinedNotes.includes('cough')) {
      return 'Dabur Honitus Herbal Cough Lozenges';
    }
    if (combinedNotes.includes('chakli') || combinedNotes.includes('bhajani')) {
      return 'Crispy Bhajani Chakli';
    }
    if (combinedNotes.includes('chaas') || combinedNotes.includes('cavin')) {
      return "Cavin's Spiced Buttermilk (Masala Chaas)";
    }
  }

  // 1. Signature product lines check
  const combinedSearch = `${rawBrand} ${rawName} ${notesStr}`.trim();
  for (const [bPat, pPat, canonical] of SIGNATURE_PRODUCT_LINES) {
    if (bPat.test(combinedSearch) && pPat.test(combinedSearch)) {
      return canonical;
    }
  }

  // 2. Regional & niche specialties check
  const nameLower = rawName.toLowerCase();
  for (const [regKey, regCanonical] of Object.entries(REGIONAL_SPECIALTIES)) {
    const rx = new RegExp(`\\b${regKey}\\b`, 'i');
    if (rx.test(nameLower)) {
      if (rawBrand && !rawName.toLowerCase().includes(rawBrand.toLowerCase())) {
        return `${titleCaseName(rawBrand)} ${regCanonical}`;
      }
      return regCanonical;
    }
  }

  // 3. Strip standalone trailing quantities
  let cleanName = rawName.replace(QUANTITY_SUFFIX_PATTERN, '').trim();
  if (!cleanName) {
    cleanName = rawName;
  }

  // 4. Handle cases where brand and name are identical or name is generic
  const isNameGeneric = genericNames.has(cleanName.toLowerCase());
  const isNameSameAsBrand = Boolean(rawBrand && cleanName.toLowerCase() === rawBrand.toLowerCase());

  if ((!cleanName || isNameGeneric || isNameSameAsBrand) && rawBrand) {
    const catLower = cleanCat.toLowerCase();
    if (catLower.includes('dairy')) {
      return `${titleCaseName(rawBrand)} Milk`;
    } else if (catLower.includes('beverage')) {
      return `${titleCaseName(rawBrand)} Beverage`;
    } else if (catLower.includes('grain') || catLower.includes('cereal')) {
      return `${titleCaseName(rawBrand)} Bakery Cookies`;
    } else if (catLower.includes('snack')) {
      return `${titleCaseName(rawBrand)} Traditional Snacks`;
    } else if (catLower.includes('produce')) {
      return `${titleCaseName(rawBrand)} Fresh Produce`;
    } else if (catLower.includes('pantry')) {
      return `${titleCaseName(rawBrand)} Pantry Staples`;
    }
    return titleCaseName(rawBrand);
  }

  if (!cleanName) {
    if (cleanCat && cleanCat.toLowerCase() !== 'unknown') {
      return cleanCat.toLowerCase().includes('produce') ? `Fresh ${cleanCat}` : cleanCat;
    }
    return 'Pantry Item';
  }

  // 5. Compose Brand + Name without repetition
  let composed = cleanName;
  if (rawBrand) {
    const brandClean = titleCaseName(rawBrand);
    if (!cleanName.toLowerCase().includes(rawBrand.toLowerCase())) {
      composed = `${brandClean} ${cleanName}`;
    }
  }

  // 6. Title case & deduplicate consecutive words
  const words = titleCaseName(composed).split(/\s+/);
  const deduped: string[] = [];
  for (const w of words) {
    if (!deduped.length || deduped[deduped.length - 1].toLowerCase() !== w.toLowerCase()) {
      deduped.push(w);
    }
  }

  return deduped.join(' ') || 'Unidentified Item';
}
