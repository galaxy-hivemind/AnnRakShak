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
};

export const categoryImages: Record<string, string> = {
  'Dairy & Eggs': eggsImg,
  'Fresh Produce': tomatoesImg,
  'Grains & Cereals': grainsImg,
  Snacks: snacksImg,
  Beverages: juiceImg,
  'Pantry Staples': pantryImg,
};

export function resolveFoodImage(item?: {
  name?: string;
  category?: string;
  image?: string;
}): string {
  if (!item) return tomatoesImg;

  // If a real image was provided (data URI, uploads, or static jpg/png from assets) and not a generic SVG
  if (
    item.image &&
    !item.image.endsWith('.svg') &&
    (item.image.startsWith('data:') ||
      item.image.startsWith('/captures/') ||
      item.image.startsWith('http') ||
      item.image.includes('/assets/'))
  ) {
    return item.image;
  }

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
