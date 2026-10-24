"""
Generate clean, premium SVG vector assets for all 210 household items.
Outputs to:
  - frontend/public/household/{id}.svg
  - captures/household/{id}.svg
"""

import os
from pathlib import Path
from household_catalog import HOUSEHOLD_CATALOG, HouseholdItem


def render_svg_card(item: HouseholdItem) -> str:
    """Generate a 400x400 vector card matching AnnaRakshak's clean studio aesthetic."""
    accent = item.accent_color
    badge = item.badge_color

    # Distinct graphic elements based on icon_type
    graphic_svg = ""
    if item.icon_type == "bottle":
        graphic_svg = f"""
        <!-- Bottle Graphic -->
        <defs>
          <linearGradient id="liquidGrad_{item.id}" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="{accent}" stop-opacity="0.8"/>
            <stop offset="50%" stop-color="{accent}" stop-opacity="0.95"/>
            <stop offset="100%" stop-color="{accent}" stop-opacity="0.75"/>
          </linearGradient>
        </defs>
        <!-- Shadow -->
        <ellipse cx="200" cy="245" rx="55" ry="12" fill="#000000" fill-opacity="0.08"/>
        <!-- Bottle Body -->
        <rect x="165" y="115" width="70" height="120" rx="16" fill="url(#liquidGrad_{item.id})" stroke="#FFFFFF" stroke-width="2"/>
        <!-- Neck -->
        <path d="M185 85 L215 85 L215 115 L185 115 Z" fill="{accent}" opacity="0.9"/>
        <!-- Cap -->
        <rect x="180" y="75" width="40" height="12" rx="3" fill="{badge}"/>
        <!-- Bottle Highlight -->
        <line x1="175" y1="125" x2="175" y2="215" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" opacity="0.4"/>
        """
    elif item.icon_type == "cookie":
        graphic_svg = f"""
        <!-- Cookie Graphic -->
        <ellipse cx="200" cy="245" rx="65" ry="14" fill="#000000" fill-opacity="0.08"/>
        <!-- Back Biscuit -->
        <circle cx="175" cy="165" r="42" fill="{accent}" opacity="0.85" stroke="#B45309" stroke-width="2"/>
        <circle cx="160" cy="155" r="3" fill="#78350F" opacity="0.6"/>
        <circle cx="185" cy="150" r="3" fill="#78350F" opacity="0.6"/>
        <circle cx="170" cy="175" r="3" fill="#78350F" opacity="0.6"/>
        <!-- Front Biscuit -->
        <circle cx="215" cy="175" r="46" fill="{accent}" stroke="#92400E" stroke-width="2.5"/>
        <circle cx="200" cy="165" r="3.5" fill="#78350F" opacity="0.7"/>
        <circle cx="230" cy="160" r="3.5" fill="#78350F" opacity="0.7"/>
        <circle cx="205" cy="190" r="3.5" fill="#78350F" opacity="0.7"/>
        <circle cx="225" cy="185" r="3.5" fill="#78350F" opacity="0.7"/>
        <circle cx="215" cy="172" r="3" fill="#B45309" opacity="0.8"/>
        """
    elif item.icon_type == "bread":
        graphic_svg = f"""
        <!-- Bread Loaf Graphic -->
        <ellipse cx="200" cy="245" rx="70" ry="14" fill="#000000" fill-opacity="0.08"/>
        <!-- Loaf Body -->
        <rect x="140" y="145" width="120" height="85" rx="14" fill="{accent}" stroke="#92400E" stroke-width="2"/>
        <!-- Loaf Top Dome -->
        <ellipse cx="200" cy="145" rx="60" ry="32" fill="#B45309"/>
        <path d="M150 140 Q200 120 250 140" stroke="#FDE68A" stroke-width="3" fill="none" opacity="0.6"/>
        <!-- Slices Lines -->
        <line x1="170" y1="140" x2="170" y2="225" stroke="#78350F" stroke-width="2" opacity="0.3"/>
        <line x1="200" y1="135" x2="200" y2="225" stroke="#78350F" stroke-width="2" opacity="0.3"/>
        <line x1="230" y1="140" x2="230" y2="225" stroke="#78350F" stroke-width="2" opacity="0.3"/>
        """
    elif item.icon_type == "jar":
        graphic_svg = f"""
        <!-- Jar Graphic -->
        <ellipse cx="200" cy="245" rx="55" ry="12" fill="#000000" fill-opacity="0.08"/>
        <!-- Jar Body -->
        <rect x="155" y="115" width="90" height="115" rx="12" fill="{accent}" opacity="0.9" stroke="#E5E7EB" stroke-width="2"/>
        <!-- Label Area -->
        <rect x="165" y="140" width="70" height="60" rx="6" fill="#FAF7F2" stroke="#D1D5DB" stroke-width="1.5"/>
        <line x1="175" y1="160" x2="225" y2="160" stroke="{badge}" stroke-width="3" stroke-linecap="round"/>
        <line x1="180" y1="175" x2="220" y2="175" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
        <line x1="185" y1="185" x2="215" y2="185" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round"/>
        <!-- Lid -->
        <rect x="162" y="95" width="76" height="22" rx="4" fill="{badge}"/>
        <line x1="165" y1="102" x2="235" y2="102" stroke="#FFFFFF" stroke-width="1.5" opacity="0.5"/>
        """
    elif item.icon_type == "bag":
        graphic_svg = f"""
        <!-- Bag / Sack Graphic -->
        <ellipse cx="200" cy="245" rx="65" ry="14" fill="#000000" fill-opacity="0.08"/>
        <path d="M150 120 L250 120 L260 235 L140 235 Z" fill="{accent}" stroke="#92400E" stroke-width="2" opacity="0.95"/>
        <path d="M140 120 Q200 135 260 120 L255 105 Q200 115 145 105 Z" fill="#92400E"/>
        <!-- Wheat / Grain Stalk Motif -->
        <circle cx="200" cy="175" r="22" fill="#FAF7F2" opacity="0.9"/>
        <path d="M195 185 Q200 165 205 185" stroke="{badge}" stroke-width="2.5" fill="none"/>
        <circle cx="200" cy="165" r="3" fill="{badge}"/>
        """
    elif item.icon_type == "box":
        graphic_svg = f"""
        <!-- Box Graphic -->
        <ellipse cx="200" cy="245" rx="60" ry="12" fill="#000000" fill-opacity="0.08"/>
        <rect x="150" y="100" width="100" height="135" rx="8" fill="{accent}" stroke="#1E293B" stroke-width="1.5"/>
        <!-- Front Design Band -->
        <rect x="150" y="135" width="100" height="55" fill="#FAF7F2" opacity="0.95"/>
        <line x1="165" y1="155" x2="235" y2="155" stroke="{badge}" stroke-width="3" stroke-linecap="round"/>
        <circle cx="200" cy="172" r="6" fill="{accent}"/>
        """
    elif item.icon_type == "carton":
        graphic_svg = f"""
        <!-- Gable Top Carton Graphic -->
        <ellipse cx="200" cy="245" rx="55" ry="12" fill="#000000" fill-opacity="0.08"/>
        <rect x="160" y="125" width="80" height="110" rx="6" fill="{accent}" opacity="0.95" stroke="#FFFFFF" stroke-width="2"/>
        <!-- Gable Top Slant -->
        <polygon points="160,125 185,85 215,85 240,125" fill="{badge}"/>
        <rect x="190" y="75" width="20" height="12" fill="#E5E7EB"/>
        <!-- Label Splash -->
        <ellipse cx="200" cy="175" rx="25" ry="25" fill="#FFFFFF" opacity="0.3"/>
        <circle cx="200" cy="175" r="14" fill="#FFFFFF" opacity="0.8"/>
        """
    elif item.icon_type == "bowl":
        graphic_svg = f"""
        <!-- Bowl Graphic -->
        <ellipse cx="200" cy="245" rx="65" ry="12" fill="#000000" fill-opacity="0.08"/>
        <path d="M140 160 Q200 240 260 160 Z" fill="#E5E7EB" stroke="#9CA3AF" stroke-width="2"/>
        <ellipse cx="200" cy="160" rx="60" ry="18" fill="{accent}"/>
        <ellipse cx="200" cy="158" rx="48" ry="12" fill="#FFFFFF" opacity="0.5"/>
        """
    elif item.icon_type == "block":
        graphic_svg = f"""
        <!-- Block Graphic (Cheese/Butter/Chocolate) -->
        <ellipse cx="200" cy="245" rx="65" ry="12" fill="#000000" fill-opacity="0.08"/>
        <!-- 3D Block -->
        <polygon points="150,150 220,120 265,140 195,170" fill="{accent}"/>
        <polygon points="150,150 195,170 195,225 150,205" fill="{accent}" opacity="0.85"/>
        <polygon points="195,170 265,140 265,195 195,225" fill="{accent}" opacity="0.7"/>
        """
    elif item.icon_type == "cup":
        graphic_svg = f"""
        <!-- Cup Graphic -->
        <ellipse cx="200" cy="245" rx="50" ry="10" fill="#000000" fill-opacity="0.08"/>
        <polygon points="160,135 240,135 225,230 175,230" fill="{accent}" stroke="#E5E7EB" stroke-width="2"/>
        <ellipse cx="200" cy="135" rx="40" ry="12" fill="{badge}"/>
        <ellipse cx="200" cy="133" rx="32" ry="8" fill="#FFFFFF" opacity="0.4"/>
        """
    else:  # produce / default
        graphic_svg = f"""
        <!-- Produce Graphic -->
        <ellipse cx="200" cy="245" rx="60" ry="12" fill="#000000" fill-opacity="0.08"/>
        <!-- Main Produce Silhouette -->
        <circle cx="200" cy="170" r="50" fill="{accent}" stroke="#FFFFFF" stroke-width="2"/>
        <!-- Leaf / Stem -->
        <path d="M200 120 Q205 100 225 105 Q215 125 200 120 Z" fill="#15803D"/>
        <path d="M198 120 L195 110" stroke="#78350F" stroke-width="3" stroke-linecap="round"/>
        <!-- Highlight -->
        <ellipse cx="182" cy="152" rx="14" ry="8" fill="#FFFFFF" opacity="0.3" transform="rotate(-30 182 152)"/>
        """

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="100%" height="100%">
  <!-- Background Studio Canvas -->
  <rect width="400" height="400" rx="24" fill="#FAF7F2"/>
  <rect x="12" y="12" width="376" height="376" rx="18" fill="none" stroke="#E6DFD5" stroke-width="1.5"/>

  <!-- Category Pill Badge -->
  <g transform="translate(24, 24)">
    <rect x="0" y="0" width="150" height="28" rx="14" fill="{badge}"/>
    <text x="75" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" font-weight="700" fill="#FFFFFF" text-anchor="middle" letter-spacing="0.5">
      {item.category.upper()}
    </text>
  </g>

  <!-- Verified Household Catalog Chip -->
  <g transform="translate(285, 24)">
    <rect x="0" y="0" width="90" height="28" rx="14" fill="#FFFFFF" stroke="#E6DFD5" stroke-width="1"/>
    <text x="45" y="18" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" font-weight="600" fill="#4B5563" text-anchor="middle">
      CATALOG
    </text>
  </g>

  <!-- Center Artwork Graphic -->
  {graphic_svg}

  <!-- Bottom Details Card -->
  <g transform="translate(24, 275)">
    <rect x="0" y="0" width="352" height="96" rx="16" fill="#FFFFFF" stroke="#E6DFD5" stroke-width="1"/>
    <!-- Title -->
    <text x="20" y="36" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="18" font-weight="800" fill="#111827">
      {item.name}
    </text>
    <!-- Subtitle -->
    <text x="20" y="60" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="12" font-weight="500" fill="#6B7280">
      {item.subtitle}
    </text>
    <!-- Footer Tag -->
    <text x="20" y="82" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="10" font-weight="700" fill="{badge}" letter-spacing="0.3">
      ★ ANNARAKSHAK HOUSEHOLD STANDARD
    </text>
  </g>
</svg>
"""
    return svg


def main():
    frontend_dir = Path("frontend/public/household")
    captures_dir = Path("captures/household")

    frontend_dir.mkdir(parents=True, exist_ok=True)
    captures_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for item in HOUSEHOLD_CATALOG:
        svg_content = render_svg_card(item)

        f_path = frontend_dir / f"{item.id}.svg"
        c_path = captures_dir / f"{item.id}.svg"

        f_path.write_text(svg_content, encoding="utf-8")
        c_path.write_text(svg_content, encoding="utf-8")
        count += 1

    print(f"Successfully generated {count} SVG assets in frontend/public/household and captures/household.")


if __name__ == "__main__":
    main()
