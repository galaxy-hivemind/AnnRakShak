import milkImg from '@/assets/food-milk.jpg';
import tomatoesImg from '@/assets/food-tomatoes.jpg';
import carrotsImg from '@/assets/food-carrots.jpg';
import spinachImg from '@/assets/food-spinach.jpg';
import eggsImg from '@/assets/food-eggs.jpg';
import yogurtImg from '@/assets/food-yogurt.jpg';
import cheeseImg from '@/assets/food-cheese.jpg';
import breadImg from '@/assets/food-bread.jpg';
import bananasImg from '@/assets/food-bananas.jpg';
import juiceImg from '@/assets/food-juice.jpg';
import grainsImg from '@/assets/cat-grains.jpg';
import snacksImg from '@/assets/cat-snacks.jpg';
import pantryImg from '@/assets/cat-pantry.jpg';

import milkPreset from '@/assets/presets/milk.jpg';
import grapesPreset from '@/assets/presets/grapes.jpg';
import carrotPreset from '@/assets/presets/carrot.jpg';
import cabbagePreset from '@/assets/presets/cabbage.jpg';
import spinachPreset from '@/assets/presets/spinach.jpg';
import chocolatePreset from '@/assets/presets/chocolate.jpg';

export {
  milkImg,
  tomatoesImg,
  carrotsImg,
  spinachImg,
  eggsImg,
  yogurtImg,
  cheeseImg,
  breadImg,
  bananasImg,
  juiceImg,
  grainsImg,
  snacksImg,
  pantryImg,
  milkPreset,
  grapesPreset,
  carrotPreset,
  cabbagePreset,
  spinachPreset,
  chocolatePreset,
};

export const categoryImages: Record<string, string> = {
  'Dairy & Eggs': eggsImg,
  'Fresh Produce': tomatoesImg,
  'Grains & Cereals': grainsImg,
  Snacks: snacksImg,
  Beverages: juiceImg,
  'Pantry Staples': pantryImg,
};

export interface DemoPreset {
  key: string;
  label: string;
  image: string;
  backendPath: string;
  category: 'Dairy & Eggs' | 'Fresh Produce' | 'Snacks' | 'Beverages' | 'Pantry Staples' | 'Grains & Cereals';
  produce?: 'Vegetable' | 'Fruit';
  quantity: string;
  storage: 'Fridge' | 'Pantry' | 'Freezer';
}

export const DEMO_PRESETS: Record<string, DemoPreset> = {
  milk: {
    key: 'milk',
    label: 'Milk',
    image: milkPreset,
    backendPath: '/presets/milk.jpg',
    category: 'Dairy & Eggs',
    quantity: '1 L',
    storage: 'Fridge',
  },
  grapes: {
    key: 'grapes',
    label: 'Grapes',
    image: grapesPreset,
    backendPath: '/presets/grapes.jpg',
    category: 'Fresh Produce',
    produce: 'Fruit',
    quantity: '400 g',
    storage: 'Fridge',
  },
  carrot: {
    key: 'carrot',
    label: 'Carrot',
    image: carrotPreset,
    backendPath: '/presets/carrot.jpg',
    category: 'Fresh Produce',
    produce: 'Vegetable',
    quantity: '500 g',
    storage: 'Fridge',
  },
  cabbage: {
    key: 'cabbage',
    label: 'Cabbage',
    image: cabbagePreset,
    backendPath: '/presets/cabbage.jpg',
    category: 'Fresh Produce',
    produce: 'Vegetable',
    quantity: '1 head',
    storage: 'Fridge',
  },
  spinach: {
    key: 'spinach',
    label: 'Spinach',
    image: spinachPreset,
    backendPath: '/presets/spinach.jpg',
    category: 'Fresh Produce',
    produce: 'Vegetable',
    quantity: '250 g',
    storage: 'Fridge',
  },
  chocolate: {
    key: 'chocolate',
    label: 'Chocolate',
    image: chocolatePreset,
    backendPath: '/presets/chocolate.jpg',
    category: 'Snacks',
    quantity: '100 g',
    storage: 'Pantry',
  },
};

export function matchPresetFood(name?: string, image?: string): DemoPreset | null {
  const check = `${name || ''} ${image || ''}`.toLowerCase().trim();
  if (!check) return null;

  if (check.includes('spinach') || check.includes('palak')) return DEMO_PRESETS.spinach;
  if (check.includes('milk') || check.includes('doodh')) return DEMO_PRESETS.milk;
  if (check.includes('grape') || check.includes('angoor')) return DEMO_PRESETS.grapes;
  if (check.includes('carrot') || check.includes('gajar')) return DEMO_PRESETS.carrot;
  if (check.includes('cabbage') || check.includes('patta gobhi') || check.includes('gobhi') || check.includes('banda gobhi')) return DEMO_PRESETS.cabbage;
  if (check.includes('chocolate') || check.includes('choco') || check.includes('cocoa')) return DEMO_PRESETS.chocolate;

  return null;
}

export function resolveFoodImage(item?: {
  name?: string;
  category?: string;
  image?: string;
}): string {
  if (!item) return tomatoesImg;

  // Direct match for preset demo items
  const preset = matchPresetFood(item.name, item.image);
  if (preset) {
    return preset.image;
  }

  // If a real image was provided (data URI, uploads, or static jpg/png from assets/presets) and not a generic SVG
  if (
    item.image &&
    !item.image.endsWith('.svg') &&
    (item.image.startsWith('data:') ||
      item.image.startsWith('/captures/') ||
      item.image.startsWith('/api/') ||
      item.image.startsWith('http') ||
      item.image.startsWith('/presets/') ||
      item.image.includes('/assets/'))
  ) {
    return item.image;
  }

  if (preset) return preset.image;

  const name = (item.name || '').toLowerCase();

  // Common refrigerator and pantry items matching
  if (name.includes('milk')) return milkImg;
  if (name.includes('tomato')) return tomatoesImg;
  if (name.includes('carrot')) return carrotsImg;
  if (name.includes('spinach') || name.includes('palak')) return spinachImg;
  if (name.includes('egg')) return eggsImg;
  if (name.includes('yogurt') || name.includes('curd') || name.includes('dahi') || name.includes('paneer')) {
    return yogurtImg;
  }
  if (name.includes('cheese') || name.includes('butter')) return cheeseImg;
  if (name.includes('bread') || name.includes('toast') || name.includes('roti') || name.includes('bun')) {
    return breadImg;
  }
  if (name.includes('banana')) return bananasImg;
  if (
    name.includes('juice') ||
    name.includes('water') ||
    name.includes('drink') ||
    name.includes('beverage') ||
    name.includes('tea') ||
    name.includes('coffee')
  ) {
    return juiceImg;
  }
  if (
    name.includes('oat') ||
    name.includes('rice') ||
    name.includes('cereal') ||
    name.includes('corn flake') ||
    name.includes('pasta') ||
    name.includes('wheat')
  ) {
    return grainsImg;
  }
  if (
    name.includes('nut') ||
    name.includes('chocolate') ||
    name.includes('biscuit') ||
    name.includes('cookie') ||
    name.includes('snack')
  ) {
    return snacksImg;
  }
  if (
    name.includes('oil') ||
    name.includes('peanut butter') ||
    name.includes('honey') ||
    name.includes('ketchup') ||
    name.includes('sauce') ||
    name.includes('salt') ||
    name.includes('spice') ||
    name.includes('chickpea')
  ) {
    return pantryImg;
  }

  // Category fallback
  if (item.category && categoryImages[item.category]) {
    return categoryImages[item.category];
  }

  return tomatoesImg;
}
