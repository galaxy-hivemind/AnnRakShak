/**
 * AnnaRakshak — 200 Common Household Items Catalog (Frontend Tier 3)
 * =================================================================
 * High-fidelity catalog of 200+ common grocery, pantry, dairy, produce,
 * snack, beverage, spice, oil, and bakery items.
 */

export interface HouseholdCatalogItem {
  id: string;
  name: string;
  subtitle: string;
  category: 'Dairy & Eggs' | 'Fresh Produce' | 'Grains & Cereals' | 'Snacks' | 'Beverages' | 'Pantry Staples';
  aliases: string[];
  image: string;
}

export const HOUSEHOLD_CATALOG: HouseholdCatalogItem[] = [
  // 1. Dairy, Plant Milk & Eggs
  { id: 'milk', name: 'Fresh Cow Milk', subtitle: 'Whole Farm Milk & Toned Doodh', category: 'Dairy & Eggs', image: '/household/milk.svg', aliases: ['milk', 'cow milk', 'toned milk', 'whole milk', 'doodh', 'amul milk', 'fresh milk', 'buffalo milk'] },
  { id: 'curd', name: 'Fresh Curd / Dahi', subtitle: 'Creamy Natural Dahi', category: 'Dairy & Eggs', image: '/household/curd.svg', aliases: ['curd', 'dahi', 'plain curd', 'plain dahi', 'yogurt', 'natural curd', 'mother dairy dahi'] },
  { id: 'greek-yogurt', name: 'Greek Yogurt', subtitle: 'Thick High-Protein Strained Yogurt', category: 'Dairy & Eggs', image: '/household/greek-yogurt.svg', aliases: ['greek yogurt', 'strained yogurt', 'epigamia greek yogurt', 'protein yogurt'] },
  { id: 'flavored-yogurt', name: 'Fruit Flavored Yogurt', subtitle: 'Strawberry, Mango & Berry Yogurt', category: 'Dairy & Eggs', image: '/household/flavored-yogurt.svg', aliases: ['flavored yogurt', 'fruit yogurt', 'strawberry yogurt', 'mango yogurt', 'blueberry yogurt'] },
  { id: 'paneer', name: 'Fresh Malai Paneer', subtitle: 'Soft Cottage Cheese Blocks', category: 'Dairy & Eggs', image: '/household/paneer.svg', aliases: ['paneer', 'cottage cheese', 'malai paneer', 'fresh paneer', 'amul paneer'] },
  { id: 'tofu', name: 'Organic Soya Tofu', subtitle: 'Plant-Based Soya Curd Blocks', category: 'Dairy & Eggs', image: '/household/tofu.svg', aliases: ['tofu', 'soya tofu', 'soy paneer', 'bean curd'] },
  { id: 'butter', name: 'Creamy Table Butter', subtitle: 'Salted & Unsalted Rich Butter', category: 'Dairy & Eggs', image: '/household/butter.svg', aliases: ['butter', 'salted butter', 'amul butter', 'table butter', 'makhan', 'butter block'] },
  { id: 'white-butter', name: 'Desi White Butter', subtitle: 'Cultured Safed Makhan', category: 'Dairy & Eggs', image: '/household/white-butter.svg', aliases: ['white butter', 'safed makhan', 'cultured butter', 'desi makhan'] },
  { id: 'ghee', name: 'Pure Desi Cow Ghee', subtitle: 'Traditional Bilona & Cow Ghee', category: 'Dairy & Eggs', image: '/household/ghee.svg', aliases: ['ghee', 'desi ghee', 'cow ghee', 'shuddh ghee', 'amul ghee', 'patanjali ghee'] },
  { id: 'cheddar-cheese', name: 'Cheddar Cheese Slices', subtitle: 'Rich Processed Cheese Blocks & Slices', category: 'Dairy & Eggs', image: '/household/cheddar-cheese.svg', aliases: ['cheese', 'cheese slices', 'cheddar cheese', 'processed cheese', 'amul cheese', 'cheese cubes'] },
  { id: 'mozzarella-cheese', name: 'Mozzarella Pizza Cheese', subtitle: 'Grated & Shredded Melt Cheese', category: 'Dairy & Eggs', image: '/household/mozzarella-cheese.svg', aliases: ['mozzarella', 'mozzarella cheese', 'pizza cheese', 'shredded cheese'] },
  { id: 'fresh-cream', name: 'Fresh Malai Cream', subtitle: 'Rich Cooking & Whipping Cream', category: 'Dairy & Eggs', image: '/household/fresh-cream.svg', aliases: ['fresh cream', 'malai', 'cooking cream', 'whipping cream', 'amul fresh cream'] },
  { id: 'condensed-milk', name: 'Sweetened Condensed Milk', subtitle: 'Thick Sweet Milk for Desserts', category: 'Dairy & Eggs', image: '/household/condensed-milk.svg', aliases: ['condensed milk', 'milkmaid', 'mithaimate'] },
  { id: 'eggs', name: 'Farm Fresh Eggs', subtitle: 'Cage-Free White & Brown Table Eggs', category: 'Dairy & Eggs', image: '/household/eggs.svg', aliases: ['eggs', 'egg', 'anda', 'brown eggs', 'white eggs', 'egg tray'] },
  { id: 'buttermilk', name: 'Spiced Buttermilk / Chaas', subtitle: 'Jeera Masala Refreshing Chaas', category: 'Dairy & Eggs', image: '/household/buttermilk.svg', aliases: ['buttermilk', 'chaas', 'chhas', 'masala chaas', 'mattha'] },
  { id: 'lassi', name: 'Sweet Punjabi Lassi', subtitle: 'Rich Creamy Mango & Sweet Lassi', category: 'Dairy & Eggs', image: '/household/lassi.svg', aliases: ['lassi', 'mango lassi', 'sweet lassi', 'punjabi lassi'] },
  { id: 'soy-milk', name: 'Unsweetened Soya Milk', subtitle: 'Dairy-Free Plant Protein Milk', category: 'Dairy & Eggs', image: '/household/soy-milk.svg', aliases: ['soy milk', 'soya milk', 'plant milk', 'sofit'] },
  { id: 'almond-milk', name: 'Pure Almond Milk', subtitle: 'Nutrient-Dense Roasted Badam Milk', category: 'Dairy & Eggs', image: '/household/almond-milk.svg', aliases: ['almond milk', 'badam milk', 'raw pressery almond milk'] },
  { id: 'oat-milk', name: 'Creamy Barista Oat Milk', subtitle: 'Plant-Based Whole Grain Milk', category: 'Dairy & Eggs', image: '/household/oat-milk.svg', aliases: ['oat milk', 'oat beverage', 'oatly'] },
  { id: 'mayonnaise', name: 'Creamy Eggless Mayonnaise', subtitle: 'Sandwich & Burger Spread', category: 'Dairy & Eggs', image: '/household/mayonnaise.svg', aliases: ['mayonnaise', 'mayo', 'eggless mayo', 'veeba mayo', 'garlic mayo'] },

  // 2. Grains, Flours & Cereals
  { id: 'wheat-flour', name: 'Chakki Whole Wheat Atta', subtitle: 'Stone-Ground Whole Wheat Roti Flour', category: 'Grains & Cereals', image: '/household/wheat-flour.svg', aliases: ['atta', 'wheat flour', 'chakki atta', 'gehun atta', 'aashirvaad atta', 'whole wheat flour'] },
  { id: 'maida', name: 'All-Purpose Flour / Maida', subtitle: 'Refined Wheat Flour for Baking', category: 'Grains & Cereals', image: '/household/maida.svg', aliases: ['maida', 'all purpose flour', 'refined flour', 'white flour'] },
  { id: 'besan', name: 'Chana Dal Besan / Gram Flour', subtitle: 'Fine Pure Bengal Gram Flour', category: 'Grains & Cereals', image: '/household/besan.svg', aliases: ['besan', 'gram flour', 'chana flour', 'chickpea flour', 'bengal gram flour'] },
  { id: 'rice-flour', name: 'Fine Rice Flour', subtitle: 'Chawal ka Atta for Dosas & Sweets', category: 'Grains & Cereals', image: '/household/rice-flour.svg', aliases: ['rice flour', 'chawal ka atta', 'arisi maavu'] },
  { id: 'basmati-rice', name: 'Royal Basmati Rice', subtitle: 'Aged Long Grain Fragrant Biryani Rice', category: 'Grains & Cereals', image: '/household/basmati-rice.svg', aliases: ['basmati rice', 'biryani rice', 'aged basmati', 'daawat basmati', 'india gate basmati'] },
  { id: 'sona-masoori-rice', name: 'Sona Masoori Rice', subtitle: 'Daily Medium Grain Soft Cooked Rice', category: 'Grains & Cereals', image: '/household/sona-masoori-rice.svg', aliases: ['sona masoori', 'raw rice', 'white rice', 'chawal', 'boiled rice', 'steamed rice'] },
  { id: 'brown-rice', name: 'Whole Grain Brown Rice', subtitle: 'Unpolished Nutrient-Rich Fiber Rice', category: 'Grains & Cereals', image: '/household/brown-rice.svg', aliases: ['brown rice', 'unpolished rice', 'red rice'] },
  { id: 'poha', name: 'Flattened Rice / Poha', subtitle: 'Thick & Thin Flaked Rice', category: 'Grains & Cereals', image: '/household/poha.svg', aliases: ['poha', 'flattened rice', 'aval', 'atukulu', 'thick poha', 'thin poha'] },
  { id: 'rolled-oats', name: 'Whole Rolled Oats', subtitle: 'Breakfast Porridge & High-Fiber Oats', category: 'Grains & Cereals', image: '/household/rolled-oats.svg', aliases: ['oats', 'rolled oats', 'quaker oats', 'instant oats', 'masala oats'] },
  { id: 'rava-sooji', name: 'Roasted Sooji / Semolina', subtitle: 'Granular Rava for Upma & Halwa', category: 'Grains & Cereals', image: '/household/rava-sooji.svg', aliases: ['sooji', 'suji', 'rava', 'semolina', 'bombay rava'] },
  { id: 'cornflakes', name: 'Crisp Corn Flakes', subtitle: 'Golden Toasted Breakfast Cereal', category: 'Grains & Cereals', image: '/household/cornflakes.svg', aliases: ['cornflakes', 'corn flakes', 'kelloggs cornflakes', 'breakfast cereal', 'cereal'] },
  { id: 'muesli', name: 'Fruit & Nut Muesli', subtitle: 'Crunchy Multigrain Clusters', category: 'Grains & Cereals', image: '/household/muesli.svg', aliases: ['muesli', 'granola', 'multigrain muesli'] },
  { id: 'quinoa', name: 'Organic White Quinoa', subtitle: 'Ancient Superfood Protein Grain', category: 'Grains & Cereals', image: '/household/quinoa.svg', aliases: ['quinoa', 'white quinoa', 'organic quinoa'] },
  { id: 'pasta-penne', name: 'Durum Wheat Penne Pasta', subtitle: 'Italian Tubular Pasta & Macaroni', category: 'Grains & Cereals', image: '/household/pasta-penne.svg', aliases: ['pasta', 'penne pasta', 'macaroni', 'fusilli', 'elbow pasta'] },
  { id: 'pasta-spaghetti', name: 'Italian Spaghetti Pasta', subtitle: 'Classic Long Wheat Pasta Strands', category: 'Grains & Cereals', image: '/household/pasta-spaghetti.svg', aliases: ['spaghetti', 'long pasta', 'fettuccine'] },
  { id: 'instant-noodles', name: 'Masala Instant Noodles', subtitle: '2-Minute Savory Wheat Noodles', category: 'Grains & Cereals', image: '/household/instant-noodles.svg', aliases: ['instant noodles', 'maggi', 'maggi noodles', 'yippee', 'ramen', 'masala noodles', 'wai wai'] },
  { id: 'hakka-noodles', name: 'Chinese Hakka Noodles', subtitle: 'Stir-Fry Steamed Noodles', category: 'Grains & Cereals', image: '/household/hakka-noodles.svg', aliases: ['hakka noodles', 'egg noodles', 'chowmein', 'veg hakka noodles'] },
  { id: 'vermicelli', name: 'Roasted Sevai / Vermicelli', subtitle: 'Semolina Strands for Kheer & Upma', category: 'Grains & Cereals', image: '/household/vermicelli.svg', aliases: ['vermicelli', 'sevai', 'sewaiya', 'semiya', 'roasted vermicelli'] },
  { id: 'sabudana', name: 'Tapioca Pearls / Sabudana', subtitle: 'Pure Sago Pearls for Khichdi', category: 'Grains & Cereals', image: '/household/sabudana.svg', aliases: ['sabudana', 'sago', 'tapioca pearls', 'sago pearls'] },
  { id: 'bajra-flour', name: 'Pearl Millet / Bajra Flour', subtitle: 'Traditional Winter Millet Flour', category: 'Grains & Cereals', image: '/household/bajra-flour.svg', aliases: ['bajra', 'bajra flour', 'pearl millet', 'kambu'] },
  { id: 'jowar-flour', name: 'Sorghum / Jowar Flour', subtitle: 'Gluten-Free Whole Grain Jowar Atta', category: 'Grains & Cereals', image: '/household/jowar-flour.svg', aliases: ['jowar', 'jowar flour', 'sorghum', 'white millet'] },
  { id: 'ragi-flour', name: 'Finger Millet / Ragi Flour', subtitle: 'Calcium-Rich Red Millet Flour', category: 'Grains & Cereals', image: '/household/ragi-flour.svg', aliases: ['ragi', 'ragi flour', 'finger millet', 'nachni', 'mandua'] },

  // 3. Pulses, Dals & Legumes
  { id: 'toor-dal', name: 'Pigeon Pea / Toor Dal', subtitle: 'Split Polished & Unpolished Arhar Dal', category: 'Pantry Staples', image: '/household/toor-dal.svg', aliases: ['toor dal', 'arhar dal', 'tuvar dal', 'split pigeon pea', 'yellow dal'] },
  { id: 'moong-dal-yellow', name: 'Split Yellow Moong Dal', subtitle: 'Skinless Washed Moong Dal', category: 'Pantry Staples', image: '/household/moong-dal-yellow.svg', aliases: ['moong dal', 'yellow moong dal', 'dhuli moong', 'split moong'] },
  { id: 'moong-dal-green', name: 'Green Chilka Moong Dal', subtitle: 'Split Green Gram with Skin', category: 'Pantry Staples', image: '/household/moong-dal-green.svg', aliases: ['chilka moong', 'split green moong', 'moong chilka'] },
  { id: 'moong-whole', name: 'Whole Green Moong', subtitle: 'Sabut Moong for Sprouting & Curries', category: 'Pantry Staples', image: '/household/moong-whole.svg', aliases: ['whole moong', 'sabut moong', 'green gram', 'sprouting moong'] },
  { id: 'chana-dal', name: 'Bengal Gram / Chana Dal', subtitle: 'Split Desi Chickpeas Dal', category: 'Pantry Staples', image: '/household/chana-dal.svg', aliases: ['chana dal', 'split chickpeas', 'bengal gram dal'] },
  { id: 'urad-dal-white', name: 'Washed White Urad Dal', subtitle: 'Skinless Urad for Idli & Dosa Batter', category: 'Pantry Staples', image: '/household/urad-dal-white.svg', aliases: ['urad dal', 'white urad dal', 'dhuli urad', 'idli dal'] },
  { id: 'urad-dal-black', name: 'Whole Black Urad / Sabut', subtitle: 'Black Gram for Dal Makhani', category: 'Pantry Staples', image: '/household/urad-dal-black.svg', aliases: ['black urad', 'sabut urad', 'kali urad', 'makhani dal'] },
  { id: 'masoor-dal-red', name: 'Split Red Masoor Dal', subtitle: 'Quick-Cooking Orange Red Lentils', category: 'Pantry Staples', image: '/household/masoor-dal-red.svg', aliases: ['masoor dal', 'red lentils', 'dhuli masoor', 'orange lentils'] },
  { id: 'masoor-whole', name: 'Whole Brown Masoor', subtitle: 'Sabut Brown Masoor Lentils', category: 'Pantry Staples', image: '/household/masoor-whole.svg', aliases: ['whole masoor', 'sabut masoor', 'brown lentils'] },
  { id: 'rajma-red', name: 'Red Kidney Beans / Rajma', subtitle: 'Plump Red & Chitra Kidney Beans', category: 'Pantry Staples', image: '/household/rajma-red.svg', aliases: ['rajma', 'kidney beans', 'red rajma', 'chitra rajma', 'jammu rajma'] },
  { id: 'kabuli-chana', name: 'White Chickpeas / Chole', subtitle: 'Plump Garbanzo Chickpeas', category: 'Pantry Staples', image: '/household/kabuli-chana.svg', aliases: ['kabuli chana', 'chole', 'white chickpeas', 'garbanzo beans', 'safed chana'] },
  { id: 'kala-chana', name: 'Brown Desi Kala Chana', subtitle: 'High-Fiber Small Brown Chickpeas', category: 'Pantry Staples', image: '/household/kala-chana.svg', aliases: ['kala chana', 'brown chickpeas', 'desi chana', 'black chickpeas'] },
  { id: 'green-peas-dry', name: 'Dried Green Peas / Matar', subtitle: 'Dried Matar for Ragda & Curries', category: 'Pantry Staples', image: '/household/green-peas-dry.svg', aliases: ['dry matar', 'dry green peas', 'hare matar', 'dried peas'] },
  { id: 'white-peas', name: 'White Peas / Safed Vatana', subtitle: 'Dried White Peas for Chaat', category: 'Pantry Staples', image: '/household/white-peas.svg', aliases: ['white vatana', 'safed vatana', 'white peas'] },
  { id: 'lobia', name: 'Black-Eyed Peas / Lobia', subtitle: 'Tender White Beans with Black Eye', category: 'Pantry Staples', image: '/household/lobia.svg', aliases: ['lobia', 'chawli', 'black eyed peas', 'cowpeas'] },
  { id: 'soya-chunks', name: 'High-Protein Soya Chunks', subtitle: 'Textured Soya Nuggets', category: 'Pantry Staples', image: '/household/soya-chunks.svg', aliases: ['soya chunks', 'nutrela', 'soya nuggets', 'soya granules', 'soya bean'] },
  { id: 'horse-gram', name: 'Kulthi / Horse Gram', subtitle: 'Traditional Rustic Superpulse', category: 'Pantry Staples', image: '/household/horse-gram.svg', aliases: ['horse gram', 'kulthi', 'gahat'] },
  { id: 'moth-beans', name: 'Matki / Moth Beans', subtitle: 'Tiny Brown Beans for Usal & Sprouts', category: 'Pantry Staples', image: '/household/moth-beans.svg', aliases: ['matki', 'moth beans', 'dew beans'] },
  { id: 'mixed-dal', name: 'Panchratna Mix Dal', subtitle: '5-Dal Blend for Rich Panchmel', category: 'Pantry Staples', image: '/household/mixed-dal.svg', aliases: ['mixed dal', 'panchratna dal', 'panchmel dal'] },
  { id: 'roasted-chana', name: 'Roasted Bengal Gram / Bhuna Chana', subtitle: 'Crunchy Crispy Snack Chana', category: 'Pantry Staples', image: '/household/roasted-chana.svg', aliases: ['roasted chana', 'bhuna chana', 'roasted gram', 'phutana'] },

  // 4. Bakery, Biscuits & Cookies
  {
    id: 'osmania-biscuits',
    name: 'Traditional Osmania Biscuits',
    subtitle: 'Deccan Bake House Sweet & Salty Tea Biscuits',
    category: 'Grains & Cereals',
    image: '/household/osmania-biscuits.svg',
    aliases: [
      'osmania biscuits', 'osmania', 'dbh osmania', 'deccan bake house',
      'dbh the deccan bake house osmania biscuits', 'dbh osmania biscuits',
      'deccan biscuits', 'hyderabadi osmania biscuits', 'osmania cookie'
    ],
  },
  { id: 'white-bread', name: 'Sandwich White Bread', subtitle: 'Soft Sliced Daily Milk Bread', category: 'Grains & Cereals', image: '/household/white-bread.svg', aliases: ['white bread', 'bread', 'sandwich bread', 'sliced bread', 'milk bread', 'britannia bread'] },
  { id: 'brown-bread', name: 'Whole Wheat Brown Bread', subtitle: 'Fiber-Rich Toasted Brown Slices', category: 'Grains & Cereals', image: '/household/brown-bread.svg', aliases: ['brown bread', 'whole wheat bread', 'atta bread'] },
  { id: 'multigrain-bread', name: 'Artisan Multigrain Bread', subtitle: 'Loaf with Seeds & Cracked Grains', category: 'Grains & Cereals', image: '/household/multigrain-bread.svg', aliases: ['multigrain bread', 'seeded bread', 'grain bread'] },
  { id: 'pav-buns', name: 'Soft Ladi Pav / Buns', subtitle: 'Puffy Bakery Pav for Vada Pav & Bhaji', category: 'Grains & Cereals', image: '/household/pav-buns.svg', aliases: ['pav', 'ladi pav', 'burger buns', 'buns', 'dinner rolls'] },
  { id: 'rusk-toast', name: 'Crunchy Suji & Elaichi Rusk', subtitle: 'Twice-Baked Crisp Tea Toast', category: 'Grains & Cereals', image: '/household/rusk-toast.svg', aliases: ['rusk', 'suji rusk', 'toast', 'britannia rusk', 'elaichi rusk', 'milk rusk'] },
  { id: 'marie-biscuits', name: 'Classic Marie Gold Biscuits', subtitle: 'Light Crisp Tea Dunking Biscuits', category: 'Grains & Cereals', image: '/household/marie-biscuits.svg', aliases: ['marie', 'marie gold', 'marie biscuits', 'britannia marie'] },
  { id: 'bourbon-biscuits', name: 'Chocolate Cream Bourbon', subtitle: 'Sugar-Dusted Cocoa Sandwich Biscuits', category: 'Grains & Cereals', image: '/household/bourbon-biscuits.svg', aliases: ['bourbon', 'bourbon biscuits', 'chocolate bourbon', 'britannia bourbon'] },
  { id: 'digestive-biscuits', name: 'NutriChoice Digestive Biscuits', subtitle: 'High-Fiber Whole Wheat Biscuits', category: 'Grains & Cereals', image: '/household/digestive-biscuits.svg', aliases: ['digestive', 'digestive biscuits', 'nutrichoice', 'fiber biscuits'] },
  { id: 'glucose-biscuits', name: 'Parle-G Glucose Biscuits', subtitle: 'Iconic Indian Wheat Energy Biscuits', category: 'Grains & Cereals', image: '/household/glucose-biscuits.svg', aliases: ['parle g', 'parle-g', 'glucose biscuits', 'parle biscuits'] },
  { id: 'cream-biscuits', name: 'Sandwich Cream Biscuits', subtitle: 'Vanilla & Chocolate Cream Treat', category: 'Grains & Cereals', image: '/household/cream-biscuits.svg', aliases: ['cream biscuits', 'treat', 'oreo', 'oreo biscuits', 'dark fantasy'] },
  {
    id: 'dry-fruit-cookies',
    name: 'Rich Dry Fruit & Cashew Cookies',
    subtitle: 'Handcrafted Bakery Cookies with Kaju & Almonds',
    category: 'Grains & Cereals',
    image: '/household/dry-fruit-cookies.svg',
    aliases: [
      'dry fruit cookies', 'cashew cookies', 'kaju cookies', 'chanduram cookies',
      "chanduram's dry fruit cookies", 'almond cookies', 'pista cookies'
    ],
  },
  { id: 'butter-cookies', name: 'Rich Danish Butter Cookies', subtitle: 'Melt-in-Mouth Golden Butter Biscuits', category: 'Grains & Cereals', image: '/household/butter-cookies.svg', aliases: ['butter cookies', 'danish cookies', 'good day', 'britannia good day'] },
  { id: 'jeera-biscuits', name: 'Salted Jeera Biscuits', subtitle: 'Roasted Cumin Savory Tea Biscuits', category: 'Grains & Cereals', image: '/household/jeera-biscuits.svg', aliases: ['jeera biscuits', 'cumin cookies', 'zeera biscuits'] },
  { id: 'nan-khatai', name: 'Cardamom Nan Khatai', subtitle: 'Traditional Indian Shortbread Cookies', category: 'Grains & Cereals', image: '/household/nan-khatai.svg', aliases: ['nan khatai', 'nankhatai', 'desi shortbread'] },
  { id: 'croissant', name: 'Flaky Butter Croissant', subtitle: 'Golden Layered French Pastry', category: 'Grains & Cereals', image: '/household/croissant.svg', aliases: ['croissant', 'butter croissant'] },
  { id: 'muffins', name: 'Choco-Chip Soft Muffins', subtitle: 'Moist Cupcakes with Cocoa Drops', category: 'Grains & Cereals', image: '/household/muffins.svg', aliases: ['muffins', 'cupcakes', 'choco muffin'] },
  { id: 'tea-cake', name: 'Fruit & Sponge Tea Cake', subtitle: 'Tutti Frutti Sliced Sponge Cake', category: 'Grains & Cereals', image: '/household/tea-cake.svg', aliases: ['tea cake', 'fruit cake', 'britannia cake', 'sponge cake', 'plum cake'] },
  { id: 'garlic-bread', name: 'Garlic Butter Baguette', subtitle: 'Herb Infused Crusty French Bread', category: 'Grains & Cereals', image: '/household/garlic-bread.svg', aliases: ['garlic bread', 'baguette'] },
  { id: 'pita-bread', name: 'Soft Mediterranean Pita Bread', subtitle: 'Pocket Bread for Hummus & Falafel', category: 'Grains & Cereals', image: '/household/pita-bread.svg', aliases: ['pita bread', 'pita pockets', 'pita'] },
  { id: 'tortilla-wraps', name: 'Flour Tortilla Wraps', subtitle: 'Soft Mexican Flatbread Wraps', category: 'Grains & Cereals', image: '/household/tortilla-wraps.svg', aliases: ['tortilla', 'wraps', 'taco shells', 'burrito wraps'] },
  { id: 'sweet-buns', name: 'Tutti Frutti Sweet Buns', subtitle: 'Sugar Glazed Bakery Buns', category: 'Grains & Cereals', image: '/household/sweet-buns.svg', aliases: ['sweet bun', 'fruit bun', 'tutti frutti bun'] },

  // 5. Beverages, Tea, Coffee & Juices
  {
    id: 'litchi-juice',
    name: 'Fresh Litchi Fruit Juice',
    subtitle: 'Sweet Lychee Nectar & Refreshing Drink',
    category: 'Beverages',
    image: '/household/litchi-juice.svg',
    aliases: [
      'litchi juice', 'tropicana frutz litchi love', 'tropicana litchi', 'frutz litchi',
      'lychee juice', 'lychee drink', 'litchi love', 'litchi drink', 'real litchi'
    ],
  },
  { id: 'mixed-fruit-juice', name: 'Mixed Fruit Juice', subtitle: 'Multi-Fruit Cocktail Nectar', category: 'Beverages', image: '/household/mixed-fruit-juice.svg', aliases: ['mixed fruit juice', 'tropicana mixed fruit', 'real mixed fruit', 'fruit punch'] },
  { id: 'orange-juice', name: 'Pure Orange Juice', subtitle: 'Citrus Morning Orange Juice with Pulp', category: 'Beverages', image: '/household/orange-juice.svg', aliases: ['orange juice', 'tropicana orange', 'real orange', 'minute maid orange'] },
  { id: 'apple-juice', name: 'Crisp Apple Juice', subtitle: 'Pure Clarified Apple Nectar', category: 'Beverages', image: '/household/apple-juice.svg', aliases: ['apple juice', 'appy fizz', 'tropicana apple', 'real apple', 'appy'] },
  { id: 'mango-drink', name: 'Rich Alphonso Mango Drink', subtitle: 'Thick Sweet Mango Pulp Beverage', category: 'Beverages', image: '/household/mango-drink.svg', aliases: ['mango drink', 'maaza', 'frooti', 'slice', 'mango juice', 'alphonso juice'] },
  { id: 'guava-juice', name: 'Pink Guava Nectar', subtitle: 'Sweet Tangy Amrud Drink with Chilli Hint', category: 'Beverages', image: '/household/guava-juice.svg', aliases: ['guava juice', 'real guava', 'pink guava', 'tropicana guava'] },
  { id: 'lemonade', name: 'Fresh Nimbu Pani / Lemonade', subtitle: 'Chilled Lemon Juice Beverage', category: 'Beverages', image: '/household/lemonade.svg', aliases: ['lemonade', 'nimbu pani', 'lemon drink', 'shikanji'] },
  { id: 'coconut-water', name: '100% Pure Coconut Water', subtitle: 'Naturally Electrolyte-Rich Tender Coconut', category: 'Beverages', image: '/household/coconut-water.svg', aliases: ['coconut water', 'nariyal pani', 'tender coconut water', 'raw pressery coconut'] },
  { id: 'black-tea', name: 'Assam Strong Black Tea', subtitle: 'Fine CTC Tea Leaves for Morning Chai', category: 'Beverages', image: '/household/black-tea.svg', aliases: ['tea', 'chai', 'black tea', 'tata tea', 'red label', 'taj mahal tea', 'wagh bakri'] },
  { id: 'green-tea', name: 'Pure Detox Green Tea', subtitle: 'Antioxidant-Rich Whole Green Tea Bags', category: 'Beverages', image: '/household/green-tea.svg', aliases: ['green tea', 'lipton green tea', 'organic india green tea', 'tetley green tea'] },
  { id: 'masala-chai', name: 'Spiced Masala Chai', subtitle: 'Tea Blended with Cardamom, Ginger & Cloves', category: 'Beverages', image: '/household/masala-chai.svg', aliases: ['masala chai', 'masala tea', 'girnar masala tea', 'spiced tea'] },
  { id: 'instant-coffee', name: 'Classic Instant Coffee', subtitle: '100% Pure Soluble Coffee Granules', category: 'Beverages', image: '/household/instant-coffee.svg', aliases: ['coffee', 'instant coffee', 'nescafe', 'bru coffee', 'nescafe classic'] },
  { id: 'filter-coffee', name: 'South Indian Filter Coffee', subtitle: 'Dark Roast Coffee & Chicory Blend', category: 'Beverages', image: '/household/filter-coffee.svg', aliases: ['filter coffee', 'coffee powder', 'cothas coffee', 'chicory coffee'] },
  { id: 'soft-drink-cola', name: 'Chilled Cola Soft Drink', subtitle: 'Refreshing Carbonated Cola Fizz', category: 'Beverages', image: '/household/soft-drink-cola.svg', aliases: ['cola', 'coke', 'thums up', 'pepsi', 'coca cola', 'diet coke'] },
  { id: 'soft-drink-lemon', name: 'Sparkling Lemon-Lime Soda', subtitle: 'Crisp Clear Sparkling Citrus Soda', category: 'Beverages', image: '/household/soft-drink-lemon.svg', aliases: ['sprite', '7up', 'limca', 'mountain dew', 'lemon soda'] },
  { id: 'packaged-water', name: 'Pure Packaged Drinking Water', subtitle: 'Ozonated & Mineral Enriched Spring Water', category: 'Beverages', image: '/household/packaged-water.svg', aliases: ['water', 'packaged drinking water', 'mineral water', 'bisleri', 'kinley', 'aquafina', 'oxyvira'] },
  { id: 'sparkling-water', name: 'Effervescent Club Soda', subtitle: 'Bubbly Carbonated Mixer Soda', category: 'Beverages', image: '/household/sparkling-water.svg', aliases: ['soda', 'club soda', 'sparkling water', 'schweppes', 'kinley soda'] },
  { id: 'energy-drink', name: 'Citrus Energy Booster', subtitle: 'Caffeinated Taurine Sparkling Drink', category: 'Beverages', image: '/household/energy-drink.svg', aliases: ['energy drink', 'red bull', 'sting', 'monster energy'] },
  { id: 'badam-milk', name: 'Kesar Badam Milk', subtitle: 'Rich Saffron Almond Flavored Drink', category: 'Beverages', image: '/household/badam-milk.svg', aliases: ['badam milk', 'kesar badam', 'almond drink', 'amul kool badam'] },
  { id: 'hot-chocolate', name: 'Rich Cocoa Drinking Chocolate', subtitle: 'Velvety Hot Chocolate Powder', category: 'Beverages', image: '/household/hot-chocolate.svg', aliases: ['hot chocolate', 'drinking chocolate', 'cadbury hot chocolate'] },
  { id: 'malt-health-drink', name: 'Malt Nutrition Drink Powder', subtitle: 'Chocolate & Malt Milk Mix', category: 'Beverages', image: '/household/malt-health-drink.svg', aliases: ['bournvita', 'horlicks', 'complan', 'boost', 'health drink'] },
  { id: 'cranberry-juice', name: 'Tart Cranberry Cocktail', subtitle: 'Vibrant Red Cranberry Nectar', category: 'Beverages', image: '/household/cranberry-juice.svg', aliases: ['cranberry juice', 'ocean spray', 'real cranberry'] },
  { id: 'pomegranate-juice', name: '100% Pomegranate Juice', subtitle: 'Ruby Anar Antioxidant Nectar', category: 'Beverages', image: '/household/pomegranate-juice.svg', aliases: ['pomegranate juice', 'anar juice', 'real pomegranate'] },
  { id: 'iced-tea', name: 'Peach & Lemon Iced Tea', subtitle: 'Chilled Brewed Refreshing Tea', category: 'Beverages', image: '/household/iced-tea.svg', aliases: ['iced tea', 'lemon iced tea', 'peach iced tea', 'nestea'] },

  // 6. Snacks, Namkeen & Savories
  { id: 'potato-chips', name: 'Classic Salted Potato Chips', subtitle: 'Thin & Crispy Golden Slices', category: 'Snacks', image: '/household/potato-chips.svg', aliases: ['potato chips', 'chips', 'lays', 'lays salted', 'classic salted chips', 'wafers'] },
  { id: 'potato-chips-masala', name: 'Indian Magic Masala Chips', subtitle: 'Spicy Tangy Seasoned Crisps', category: 'Snacks', image: '/household/potato-chips-masala.svg', aliases: ['magic masala', 'lays magic masala', 'spicy chips', 'blue lays', 'masala chips'] },
  { id: 'bhujia-sev', name: 'Bikaneri Aloo Bhujia', subtitle: 'Spicy Crisp Moth Flour Sev', category: 'Snacks', image: '/household/bhujia-sev.svg', aliases: ['bhujia', 'aloo bhujia', 'haldiram bhujia', 'bikaneri bhujia', 'sev', 'nylon sev'] },
  { id: 'mixture-namkeen', name: 'All-in-One Mixture Namkeen', subtitle: 'Crunchy Nuts, Sev, Dal & Flakes', category: 'Snacks', image: '/household/mixture-namkeen.svg', aliases: ['mixture', 'all in one mixture', 'haldiram mixture', 'khatta meetha', 'navratan mixture', 'namkeen'] },
  { id: 'kurkure-masala', name: 'Masala Munch Corn Curls', subtitle: 'Chatpata Tedhe Medhe Puffs', category: 'Snacks', image: '/household/kurkure-masala.svg', aliases: ['kurkure', 'masala munch', 'tedhe medhe', 'corn curls'] },
  { id: 'chakli', name: 'Crispy Bhajani Chakli', subtitle: 'Spiced Spiral Multi-Flour Crunch', category: 'Snacks', image: '/household/chakli.svg', aliases: ['chakli', 'bhajani chakli', 'murukku', 'charliee chakli'] },
  { id: 'khakhra', name: 'Roasted Methi Khakhra', subtitle: 'Crispy Wheat Thin Crackers', category: 'Snacks', image: '/household/khakhra.svg', aliases: ['khakhra', 'methi khakhra', 'jeera khakhra', 'gujarati khakhra'] },
  { id: 'banana-chips', name: 'Kerala Salted Banana Chips', subtitle: 'Coconut Oil Fried Crisp Raw Banana Slices', category: 'Snacks', image: '/household/banana-chips.svg', aliases: ['banana chips', 'kela chips', 'kerala banana chips'] },
  { id: 'popcorn', name: 'Golden Butter Popcorn', subtitle: 'Fluffy Popped Corn Kernels', category: 'Snacks', image: '/household/popcorn.svg', aliases: ['popcorn', 'act ii', 'butter popcorn', 'salted popcorn'] },
  { id: 'makhana', name: 'Roasted Fox Nuts / Makhana', subtitle: 'Light Herb-Tossed Lotus Seeds', category: 'Snacks', image: '/household/makhana.svg', aliases: ['makhana', 'fox nuts', 'phool makhana', 'roasted makhana'] },
  { id: 'chivda', name: 'Roasted Poha Chivda', subtitle: 'Light Peanut & Mustard Tempering Mix', category: 'Snacks', image: '/household/chivda.svg', aliases: ['chivda', 'poha chivda', 'cornflake chivda'] },
  { id: 'salted-peanuts', name: 'Roasted Salted Peanuts', subtitle: 'Toasted Golden Singdana', category: 'Snacks', image: '/household/salted-peanuts.svg', aliases: ['salted peanuts', 'peanuts', 'singdana', 'roasted peanuts'] },
  { id: 'salted-cashews', name: 'Golden Fried Salted Cashews', subtitle: 'Rich Butter Roasted Kaju', category: 'Snacks', image: '/household/salted-cashews.svg', aliases: ['salted cashews', 'kaju fry', 'roasted cashews'] },
  { id: 'nachos', name: 'Corn Tortilla Nacho Chips', subtitle: 'Jalapeno & Cheese Triangle Crisps', category: 'Snacks', image: '/household/nachos.svg', aliases: ['nachos', 'doritos', 'nacho chips', 'tortilla chips'] },
  { id: 'gathiya', name: 'Bhavnagari Besan Gathiya', subtitle: 'Soft Spiced Gram Flour Strands', category: 'Snacks', image: '/household/gathiya.svg', aliases: ['gathiya', 'bhavnagari gathiya', 'papdi gathiya'] },
  { id: 'dry-samosa', name: 'Mini Cocktail Samosa', subtitle: 'Crispy Pastry with Sweet Spiced Filling', category: 'Snacks', image: '/household/dry-samosa.svg', aliases: ['samosa', 'dry samosa', 'cocktail samosa'] },
  { id: 'bhakarwadi', name: 'Pune Spiced Bhakarwadi', subtitle: 'Pinwheel Coconut & Sesame Rolls', category: 'Snacks', image: '/household/bhakarwadi.svg', aliases: ['bhakarwadi', 'bakarwadi', 'chitale bhakarwadi'] },
  { id: 'soan-papdi', name: 'Flaky Cardamom Soan Papdi', subtitle: 'Melt-in-Mouth Cotton Sweet Cubes', category: 'Snacks', image: '/household/soan-papdi.svg', aliases: ['soan papdi', 'haldiram soan papdi', 'patisa'] },
  { id: 'chikki', name: 'Peanut Jaggery Chikki', subtitle: 'Lonavala Roasted Nut Brittle', category: 'Snacks', image: '/household/chikki.svg', aliases: ['chikki', 'peanut chikki', 'gud chikki', 'patti'] },
  { id: 'diet-namkeen', name: 'Roasted Diet Multigrain Mix', subtitle: 'Zero-Oil Light Crisp Snack', category: 'Snacks', image: '/household/diet-namkeen.svg', aliases: ['diet namkeen', 'diet mixture', 'roasted mixture'] },

  // 7. Spices, Masalas & Seasonings
  { id: 'turmeric-powder', name: 'Pure Golden Turmeric Powder', subtitle: 'Curcumin-Rich Haldi Powder', category: 'Pantry Staples', image: '/household/turmeric-powder.svg', aliases: ['turmeric', 'turmeric powder', 'haldi', 'haldi powder'] },
  { id: 'red-chilli-powder', name: 'Kashmiri Red Chilli Powder', subtitle: 'Vibrant Red Moderate Heat Mirch', category: 'Pantry Staples', image: '/household/red-chilli-powder.svg', aliases: ['red chilli powder', 'chilli powder', 'mirch powder', 'lal mirch', 'kashmiri mirch'] },
  { id: 'coriander-powder', name: 'Aromatic Dhania Powder', subtitle: 'Cold Ground Coriander Seed Powder', category: 'Pantry Staples', image: '/household/coriander-powder.svg', aliases: ['coriander powder', 'dhania powder', 'dhaniya powder'] },
  { id: 'cumin-seeds', name: 'Whole Cumin Seeds / Jeera', subtitle: 'Fragrant Unpolished Jeera', category: 'Pantry Staples', image: '/household/cumin-seeds.svg', aliases: ['cumin seeds', 'jeera', 'whole cumin', 'zeera'] },
  { id: 'cumin-powder', name: 'Roasted Jeera Powder', subtitle: 'Fresh Ground Cumin for Raitas & Chaat', category: 'Pantry Staples', image: '/household/cumin-powder.svg', aliases: ['cumin powder', 'jeera powder', 'roasted jeera'] },
  { id: 'mustard-seeds', name: 'Black Mustard Seeds / Rai', subtitle: 'Pungent Tempering Mustard Seeds', category: 'Pantry Staples', image: '/household/mustard-seeds.svg', aliases: ['mustard seeds', 'rai', 'sarson', 'black mustard seeds'] },
  { id: 'garam-masala', name: 'Royal Shahi Garam Masala', subtitle: 'Warm Spiced Blend of 15 Whole Spices', category: 'Pantry Staples', image: '/household/garam-masala.svg', aliases: ['garam masala', 'shahi garam masala', 'everest garam masala', 'mdh garam masala'] },
  { id: 'table-salt', name: 'Iodized Table Salt', subtitle: 'Vacuum Evaporated Pure Salt', category: 'Pantry Staples', image: '/household/table-salt.svg', aliases: ['salt', 'iodized salt', 'tata salt', 'namak', 'table salt'] },
  { id: 'rock-salt', name: 'Himalayan Pink Rock Salt', subtitle: 'Sendha Namak Mineral Salt', category: 'Pantry Staples', image: '/household/rock-salt.svg', aliases: ['rock salt', 'pink salt', 'sendha namak', 'himalayan salt'] },
  { id: 'black-salt', name: 'Kala Namak / Black Salt', subtitle: 'Tangy Volcanic Mineral Salt', category: 'Pantry Staples', image: '/household/black-salt.svg', aliases: ['black salt', 'kala namak'] },
  { id: 'black-pepper', name: 'Malabar Black Peppercorns', subtitle: 'Whole & Ground Kali Mirch', category: 'Pantry Staples', image: '/household/black-pepper.svg', aliases: ['black pepper', 'kali mirch', 'pepper powder', 'peppercorns'] },
  { id: 'green-cardamom', name: 'Whole Green Cardamom / Elaichi', subtitle: 'Fragrant Pods for Chai & Desserts', category: 'Pantry Staples', image: '/household/green-cardamom.svg', aliases: ['cardamom', 'green cardamom', 'elaichi', 'chhoti elaichi'] },
  { id: 'black-cardamom', name: 'Smoked Black Cardamom', subtitle: 'Bold Badi Elaichi for Biryanis', category: 'Pantry Staples', image: '/household/black-cardamom.svg', aliases: ['black cardamom', 'badi elaichi', 'moti elaichi'] },
  { id: 'cloves', name: 'Aromatic Whole Cloves / Laung', subtitle: 'Select Clove Buds', category: 'Pantry Staples', image: '/household/cloves.svg', aliases: ['cloves', 'laung', 'clove'] },
  { id: 'cinnamon', name: 'Ceylon Cinnamon Sticks / Dalchini', subtitle: 'Sweet Aromatic Tree Bark Rolls', category: 'Pantry Staples', image: '/household/cinnamon.svg', aliases: ['cinnamon', 'dalchini', 'cinnamon sticks'] },
  { id: 'fenugreek-seeds', name: 'Fenugreek Seeds / Methi Dana', subtitle: 'Bitter Aromatic Golden Seeds', category: 'Pantry Staples', image: '/household/fenugreek-seeds.svg', aliases: ['fenugreek seeds', 'methi dana', 'methi seeds'] },
  { id: 'kasuri-methi', name: 'Fragrant Kasuri Methi', subtitle: 'Sundried Fenugreek Herb Leaves', category: 'Pantry Staples', image: '/household/kasuri-methi.svg', aliases: ['kasuri methi', 'dried fenugreek', 'kasoori methi'] },
  { id: 'fennel-seeds', name: 'Sweet Green Fennel Seeds / Saunf', subtitle: 'Mouth-Freshening Lucknowi Saunf', category: 'Pantry Staples', image: '/household/fennel-seeds.svg', aliases: ['fennel seeds', 'saunf', 'variyali', 'badi saunf'] },
  { id: 'asafoetida', name: 'Compounded Asafoetida / Hing', subtitle: 'Strong Pungent Tempered Hing', category: 'Pantry Staples', image: '/household/asafoetida.svg', aliases: ['hing', 'asafoetida', 'bandhani hing', 'compounded hing'] },
  { id: 'chaat-masala', name: 'Chunky Tangy Chaat Masala', subtitle: 'Dry Mango & Mint Sprinkling Spice', category: 'Pantry Staples', image: '/household/chaat-masala.svg', aliases: ['chaat masala', 'chunky chaat masala', 'catch chaat masala'] },
  { id: 'sambhar-masala', name: 'Authentic Sambhar Powder', subtitle: 'South Indian Roasted Lentil & Spice Mix', category: 'Pantry Staples', image: '/household/sambhar-masala.svg', aliases: ['sambhar powder', 'sambhar masala', 'sambar powder'] },
  { id: 'biryani-masala', name: 'Lucknowi Biryani Masala', subtitle: 'Saffron & Rose Petal Rice Seasoning', category: 'Pantry Staples', image: '/household/biryani-masala.svg', aliases: ['biryani masala', 'shahi biryani masala'] },
  { id: 'chole-masala', name: 'Amritsari Chole Masala', subtitle: 'Dark Spiced Chickpea Seasoning', category: 'Pantry Staples', image: '/household/chole-masala.svg', aliases: ['chole masala', 'chana masala'] },
  { id: 'kitchen-king-masala', name: 'All-in-One Kitchen King Masala', subtitle: 'Everyday Curry Seasoning Blend', category: 'Pantry Staples', image: '/household/kitchen-king-masala.svg', aliases: ['kitchen king', 'kitchen king masala', 'sabji masala'] },

  // 8. Cooking Oils, Ghee & Fats
  { id: 'mustard-oil', name: 'Kachi Ghani Mustard Oil', subtitle: 'Cold-Pressed Pungent Sarson Tel', category: 'Pantry Staples', image: '/household/mustard-oil.svg', aliases: ['mustard oil', 'sarson ka tel', 'kachi ghani', 'fortune mustard oil', 'engine mustard oil'] },
  { id: 'sunflower-oil', name: 'Refined Sunflower Oil', subtitle: 'Light Heart-Friendly Frying Oil', category: 'Pantry Staples', image: '/household/sunflower-oil.svg', aliases: ['sunflower oil', 'fortune sunflower oil', 'sunflower cooking oil', 'refined oil'] },
  { id: 'groundnut-oil', name: 'Cold-Pressed Groundnut Oil', subtitle: 'Aromatic Peanut Frying Oil', category: 'Pantry Staples', image: '/household/groundnut-oil.svg', aliases: ['groundnut oil', 'peanut oil', 'mungfali tel', 'filtered groundnut oil'] },
  { id: 'olive-oil-extra-virgin', name: 'Extra Virgin Olive Oil', subtitle: 'Cold-Pressed Dressing Olive Oil', category: 'Pantry Staples', image: '/household/olive-oil-extra-virgin.svg', aliases: ['olive oil', 'extra virgin olive oil', 'evoo', 'figaro olive oil', 'borges olive oil'] },
  { id: 'olive-oil-cooking', name: 'Pure Olive Cooking Oil', subtitle: 'High Smoke Point Sauteeing Oil', category: 'Pantry Staples', image: '/household/olive-oil-cooking.svg', aliases: ['cooking olive oil', 'pomace olive oil', 'pure olive oil'] },
  { id: 'sesame-oil', name: 'Gingelly / Pure Sesame Oil', subtitle: 'Toasted Sesame Seed Cooking Oil', category: 'Pantry Staples', image: '/household/sesame-oil.svg', aliases: ['sesame oil', 'til ka tel', 'gingelly oil', 'idayam gingelly'] },
  { id: 'coconut-cooking-oil', name: 'Virgin Coconut Cooking Oil', subtitle: 'Cold-Pressed Edible Coconut Oil', category: 'Pantry Staples', image: '/household/coconut-cooking-oil.svg', aliases: ['coconut cooking oil', 'edible coconut oil', 'klf nirmal', 'kera coconut oil'] },
  { id: 'rice-bran-oil', name: 'Physically Refined Rice Bran Oil', subtitle: 'Oryzanol-Rich Balanced Oil', category: 'Pantry Staples', image: '/household/rice-bran-oil.svg', aliases: ['rice bran oil', 'fortune rice bran'] },
  { id: 'soybean-oil', name: 'Refined Soybean Cooking Oil', subtitle: 'Light All-Purpose Frying Oil', category: 'Pantry Staples', image: '/household/soybean-oil.svg', aliases: ['soybean oil', 'soya oil', 'fortune soya'] },
  { id: 'corn-oil', name: 'Pure Corn Oil', subtitle: 'Golden Maize Frying Oil', category: 'Pantry Staples', image: '/household/corn-oil.svg', aliases: ['corn oil', 'maize oil'] },
  { id: 'cow-desi-ghee', name: 'A2 Cultured Cow Desi Ghee', subtitle: 'Golden Danedar Pure Cow Ghee', category: 'Pantry Staples', image: '/household/cow-desi-ghee.svg', aliases: ['cow ghee', 'a2 cow ghee', 'amul cow ghee', 'mother dairy cow ghee'] },
  { id: 'buffalo-ghee', name: 'Rich Buffalo White Ghee', subtitle: 'Creamy Thick White Desi Ghee', category: 'Pantry Staples', image: '/household/buffalo-ghee.svg', aliases: ['buffalo ghee', 'white ghee'] },
  { id: 'vanaspati-ghee', name: 'Vegetable Vanaspati Ghee', subtitle: 'Traditional Frying Vanaspati', category: 'Pantry Staples', image: '/household/vanaspati-ghee.svg', aliases: ['vanaspati', 'dalda', 'vegetable ghee'] },
  { id: 'cooking-butter-unsalted', name: 'Unsalted Cooking Butter', subtitle: 'Pure Butter for Baking & Pastry', category: 'Pantry Staples', image: '/household/cooking-butter-unsalted.svg', aliases: ['unsalted butter', 'cooking butter', 'white butter block'] },

  // 9. Fresh Fruits & Vegetables (Produce)
  { id: 'tomatoes', name: 'Farm Fresh Tomatoes', subtitle: 'Juicy Vine-Ripened Red Tamatar', category: 'Fresh Produce', image: '/household/tomatoes.svg', aliases: ['tomato', 'tomatoes', 'tamatar', 'cherry tomatoes', 'roma tomatoes'] },
  { id: 'onions', name: 'Fresh Red Onions', subtitle: 'Crisp Pungent Nasik Red Pyaaz', category: 'Fresh Produce', image: '/household/onions.svg', aliases: ['onion', 'onions', 'pyaaz', 'red onion', 'shallots', 'sambhar onion'] },
  { id: 'potatoes', name: 'Fresh Golden Potatoes', subtitle: 'Earthy Firm Cooking Aloo', category: 'Fresh Produce', image: '/household/potatoes.svg', aliases: ['potato', 'potatoes', 'aloo', 'baby potatoes'] },
  { id: 'ginger', name: 'Fresh Root Ginger / Adrak', subtitle: 'Spicy Aromatic Ginger Rhizome', category: 'Fresh Produce', image: '/household/ginger.svg', aliases: ['ginger', 'adrak', 'fresh ginger'] },
  { id: 'garlic', name: 'Whole Garlic Bulbs', subtitle: 'Pungent White Lehsun Cloves', category: 'Fresh Produce', image: '/household/garlic.svg', aliases: ['garlic', 'lehsun', 'garlic cloves'] },
  { id: 'green-chillies', name: 'Fresh Green Chillies', subtitle: 'Spicy Slender Hari Mirch', category: 'Fresh Produce', image: '/household/green-chillies.svg', aliases: ['green chilli', 'green chillies', 'hari mirch', 'hot chillies'] },
  { id: 'lemon-fresh', name: 'Fresh Yellow Lemons', subtitle: 'Juicy Sour Nimbu', category: 'Fresh Produce', image: '/household/lemon-fresh.svg', aliases: ['lemon', 'lemons', 'nimbu', 'lime'] },
  { id: 'coriander-fresh', name: 'Fresh Coriander Leaves', subtitle: 'Aromatic Hara Dhania Bunch', category: 'Fresh Produce', image: '/household/coriander-fresh.svg', aliases: ['coriander', 'coriander leaves', 'cilantro', 'hara dhania', 'dhania patta'] },
  { id: 'curry-leaves', name: 'Fresh Curry Leaves', subtitle: 'Fragrant Kadi Patta for Tadka', category: 'Fresh Produce', image: '/household/curry-leaves.svg', aliases: ['curry leaves', 'kadi patta', 'meetha neem'] },
  { id: 'spinach-fresh', name: 'Tender Green Spinach', subtitle: 'Fresh Iron-Rich Palak Bunch', category: 'Fresh Produce', image: '/household/spinach-fresh.svg', aliases: ['spinach', 'palak', 'fresh spinach', 'baby spinach'] },
  { id: 'carrots', name: 'Crunchy Red & Orange Carrots', subtitle: 'Sweet Salad & Halwa Gajar', category: 'Fresh Produce', image: '/household/carrots.svg', aliases: ['carrot', 'carrots', 'gajar', 'red carrots', 'orange carrots'] },
  { id: 'cucumbers', name: 'Crisp Green Cucumbers', subtitle: 'Hydrating Kheera Salad Cucumbers', category: 'Fresh Produce', image: '/household/cucumbers.svg', aliases: ['cucumber', 'cucumbers', 'kheera', 'kakdi'] },
  { id: 'cabbage-fresh', name: 'Fresh Green Cabbage', subtitle: 'Crispy Layered Patta Gobhi', category: 'Fresh Produce', image: '/household/cabbage-fresh.svg', aliases: ['cabbage', 'patta gobhi', 'banda gobhi'] },
  { id: 'cauliflower', name: 'Fresh White Cauliflower', subtitle: 'Compact White Phool Gobhi Florets', category: 'Fresh Produce', image: '/household/cauliflower.svg', aliases: ['cauliflower', 'phool gobhi', 'gobi'] },
  { id: 'capsicum', name: 'Crunchy Green Capsicum', subtitle: 'Sweet Bell Pepper / Shimla Mirch', category: 'Fresh Produce', image: '/household/capsicum.svg', aliases: ['capsicum', 'bell pepper', 'green capsicum', 'shimla mirch'] },
  { id: 'bhindi', name: 'Tender Green Bhindi', subtitle: 'Fresh Crisp Okra / Ladyfinger', category: 'Fresh Produce', image: '/household/bhindi.svg', aliases: ['bhindi', 'ladyfinger', 'okra', 'bhendi'] },
  { id: 'apples-fresh', name: 'Crisp Red Royal Apples', subtitle: 'Kashmiri Sweet Table Apples', category: 'Fresh Produce', image: '/household/apples-fresh.svg', aliases: ['apple', 'apples', 'red apple', 'kashmiri apple', 'seb'] },
  { id: 'bananas-fresh', name: 'Fresh Ripe Bananas', subtitle: 'Sweet Cavendish Robusta Kela', category: 'Fresh Produce', image: '/household/bananas-fresh.svg', aliases: ['banana', 'bananas', 'kela', 'robusta banana', 'yelakki banana'] },
  { id: 'oranges-fresh', name: 'Nagpur Sweet Oranges', subtitle: 'Easy-Peel Juicy Santre', category: 'Fresh Produce', image: '/household/oranges-fresh.svg', aliases: ['orange', 'oranges', 'santra', 'santre', 'nagpur orange', 'kinnow'] },
  { id: 'grapes-fresh', name: 'Seedless Green & Black Grapes', subtitle: 'Sweet Thompson Angoor', category: 'Fresh Produce', image: '/household/grapes-fresh.svg', aliases: ['grapes', 'grape', 'angoor', 'green grapes', 'black grapes'] },
  { id: 'mangoes-fresh', name: 'Fresh Alphonso Mangoes', subtitle: 'King of Mangoes / Hapus Aam', category: 'Fresh Produce', image: '/household/mangoes-fresh.svg', aliases: ['mango', 'mangoes', 'alphonso', 'hapus', 'aam', 'kesar mango'] },
  { id: 'papaya-fresh', name: 'Ripe Red Papaya', subtitle: 'Sweet Digestive Papita', category: 'Fresh Produce', image: '/household/papaya-fresh.svg', aliases: ['papaya', 'papita'] },
  { id: 'pomegranate-fresh', name: 'Ruby Red Pomegranate', subtitle: 'Sweet Juicy Anar Pearls', category: 'Fresh Produce', image: '/household/pomegranate-fresh.svg', aliases: ['pomegranate', 'anar'] },
  { id: 'watermelon-fresh', name: 'Sweet Red Watermelon', subtitle: 'Summer Hydrating Tarbooz', category: 'Fresh Produce', image: '/household/watermelon-fresh.svg', aliases: ['watermelon', 'tarbooz'] },

  // 10. Condiments, Spreads, Sweets & Dry Fruits
  { id: 'tomato-ketchup', name: 'Rich Tomato Ketchup', subtitle: 'Tangy Table Dip & Sauce', category: 'Pantry Staples', image: '/household/tomato-ketchup.svg', aliases: ['ketchup', 'tomato ketchup', 'kissan ketchup', 'maggi sauce', 'tomato sauce'] },
  { id: 'soya-sauce', name: 'Dark Chinese Soy Sauce', subtitle: 'Fermented Salty Umami Seasoning', category: 'Pantry Staples', image: '/household/soya-sauce.svg', aliases: ['soya sauce', 'soy sauce', 'dark soy sauce', "ching's secret soy sauce"] },
  { id: 'red-chilli-sauce', name: 'Spicy Red Chilli Sauce', subtitle: 'Hot Garlic Chilli Dip', category: 'Pantry Staples', image: '/household/red-chilli-sauce.svg', aliases: ['red chilli sauce', 'chilli sauce', 'hot sauce'] },
  { id: 'green-chilli-sauce', name: 'Tangy Green Chilli Sauce', subtitle: 'Zesty Indo-Chinese Sauce', category: 'Pantry Staples', image: '/household/green-chilli-sauce.svg', aliases: ['green chilli sauce', 'green sauce'] },
  { id: 'white-vinegar', name: 'White Cooking Vinegar', subtitle: 'Pure Acetic Acid Solution for Pickling', category: 'Pantry Staples', image: '/household/white-vinegar.svg', aliases: ['vinegar', 'white vinegar', 'cooking vinegar', 'sirka'] },
  { id: 'apple-cider-vinegar', name: 'Organic Apple Cider Vinegar', subtitle: 'Raw Unfiltered ACV with The Mother', category: 'Pantry Staples', image: '/household/apple-cider-vinegar.svg', aliases: ['apple cider vinegar', 'acv', 'bragg apple cider vinegar'] },
  { id: 'peanut-butter', name: 'All-Natural Peanut Butter', subtitle: 'Creamy & Crunchy Roasted Nut Spread', category: 'Pantry Staples', image: '/household/peanut-butter.svg', aliases: ['peanut butter', 'pintola peanut butter', 'myfitness peanut butter', 'crunchy peanut butter'] },
  { id: 'mixed-fruit-jam', name: 'Mixed Fruit Sweet Jam', subtitle: 'Classic Breakfast Bread Spread', category: 'Pantry Staples', image: '/household/mixed-fruit-jam.svg', aliases: ['jam', 'mixed fruit jam', 'kissan jam', 'fruit jam'] },
  { id: 'pure-honey', name: '100% Pure Forest Honey', subtitle: 'Natural Golden Sweet Honey', category: 'Pantry Staples', image: '/household/pure-honey.svg', aliases: ['honey', 'pure honey', 'dabur honey', 'patanjali honey', 'shahad'] },
  { id: 'chocolate-spread', name: 'Cocoa Hazelnut Spread', subtitle: 'Rich Nutella Cream Spread', category: 'Pantry Staples', image: '/household/chocolate-spread.svg', aliases: ['nutella', 'chocolate spread', 'hazelnut spread', 'choco spread'] },
  { id: 'mango-pickle', name: 'Traditional Mango Pickle / Aam Achar', subtitle: 'Spicy Mustard Oil Raw Mango Pickle', category: 'Pantry Staples', image: '/household/mango-pickle.svg', aliases: ['mango pickle', 'aam ka achar', 'pickle', 'achar', "mother's recipe mango pickle"] },
  { id: 'mixed-pickle', name: 'Mixed Vegetable Pickle', subtitle: 'Pachranga Spiced Achar', category: 'Pantry Staples', image: '/household/mixed-pickle.svg', aliases: ['mixed pickle', 'pachranga achar', 'mixed veg pickle'] },
  { id: 'schezwan-chutney', name: 'Spicy Schezwan Chutney', subtitle: 'Fiery Garlic & Red Chilli Dip', category: 'Pantry Staples', image: '/household/schezwan-chutney.svg', aliases: ['schezwan chutney', 'schezwan sauce', "ching's schezwan"] },
  { id: 'dark-chocolate', name: '70% Rich Dark Chocolate', subtitle: 'Bitter-Sweet Cocoa Bean Bar', category: 'Snacks', image: '/household/dark-chocolate.svg', aliases: ['dark chocolate', 'amul dark chocolate', 'bournville', 'lindt dark'] },
  { id: 'milk-chocolate', name: 'Cadbury Dairy Milk Chocolate', subtitle: 'Creamy Smooth Milk Chocolate Bar', category: 'Snacks', image: '/household/milk-chocolate.svg', aliases: ['chocolate', 'dairy milk', 'cadbury dairy milk', 'milk chocolate', 'cadbury silk'] },
  { id: 'white-chocolate', name: 'Nestle Milkybar White Chocolate', subtitle: 'Sweet Creamy White Chocolate Bar', category: 'Snacks', image: '/household/white-chocolate.svg', aliases: ['white chocolate', 'milkybar', 'nestle milkybar', 'milky bar', 'milkybar chocolate', 'milkybar white chocolate'] },
  { id: 'almonds', name: 'California Whole Almonds / Badam', subtitle: 'Crunchy Heart-Healthy Raw Almonds', category: 'Pantry Staples', image: '/household/almonds.svg', aliases: ['almonds', 'almond', 'badam', 'california badam'] },
  { id: 'cashews', name: 'Whole Golden Cashews / Kaju', subtitle: 'Creamy Sweet Mangalore Kaju', category: 'Pantry Staples', image: '/household/cashews.svg', aliases: ['cashews', 'cashew', 'kaju', 'whole cashews'] },
  { id: 'walnuts', name: 'Raw Shelled Walnuts / Akhrot', subtitle: 'Omega-Rich Brain Food Walnut Halves', category: 'Pantry Staples', image: '/household/walnuts.svg', aliases: ['walnuts', 'walnut', 'akhrot', 'walnut kernels'] },
  { id: 'pistachios', name: 'Roasted Salted Pistachios / Pista', subtitle: 'Iranian Green Nut Kernels', category: 'Pantry Staples', image: '/household/pistachios.svg', aliases: ['pistachios', 'pista', 'salted pista', 'pistachio'] },
];

function normalize(text: string): string {
  return (text || '')
    .toLowerCase()
    .replace(/['’]s\b/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function findBestHouseholdItem(
  name?: string,
  category?: string
): HouseholdCatalogItem | null {
  if (!name && !category) return null;
  const cleanName = normalize(name || '');
  if (!cleanName) return null;

  const queryTokens = new Set(cleanName.split(' '));

  // 1. Exact alias match (full string match)
  for (const item of HOUSEHOLD_CATALOG) {
    for (const alias of item.aliases) {
      const cleanAlias = normalize(alias);
      if (cleanAlias === cleanName) return item;
    }
  }

  // 1b. Whole phrase contained - pick the most specific (longest / highest token count) phrase match
  let bestPhraseItem: HouseholdCatalogItem | null = null;
  let bestPhraseScore = 0;
  for (const item of HOUSEHOLD_CATALOG) {
    for (const alias of item.aliases) {
      const cleanAlias = normalize(alias);
      const re = new RegExp(`(^|\\s)${cleanAlias}($|\\s)`, 'i');
      if (re.test(cleanName)) {
        const pTokens = cleanAlias.split(' ').filter(Boolean).length;
        let score = pTokens * 100 + cleanAlias.length;
        if (category && item.category.toLowerCase().includes(category.toLowerCase())) {
          score += 10;
        }
        if (score > bestPhraseScore) {
          bestPhraseScore = score;
          bestPhraseItem = item;
        }
      }
    }
  }
  if (bestPhraseItem) return bestPhraseItem;

  // 2. Token overlap ranking with threshold
  let bestItem: HouseholdCatalogItem | null = null;
  let bestScore = 0;

  for (const item of HOUSEHOLD_CATALOG) {
    let score = 0;
    for (const alias of item.aliases) {
      const cleanAlias = normalize(alias);
      const aliasTokens = cleanAlias.split(' ').filter(Boolean);
      if (aliasTokens.length === 0) continue;

      const isSubset = aliasTokens.every((t) => queryTokens.has(t));
      if (isSubset) {
        score = Math.max(score, 50 + aliasTokens.length * 10);
      } else {
        const matches = aliasTokens.filter((t) => queryTokens.has(t)).length;
        if (matches > 0) {
          const ratio = matches / aliasTokens.length;
          score = Math.max(score, ratio * 35);
        }
      }
    }

    if (category && item.category.toLowerCase().includes(category.toLowerCase())) {
      score += 5;
    }

    if (score > bestScore) {
      bestScore = score;
      bestItem = item;
    }
  }

  if (bestScore >= 25) {
    return bestItem;
  }

  return null;
}
