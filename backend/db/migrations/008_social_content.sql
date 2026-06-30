-- v2.2: Social media content types (post + carousel) + Indian personas library

-- ============================================================
-- 1. Campaigns: content_type + research + carousel fields
-- ============================================================

alter table campaigns
  add column if not exists content_type text not null default 'banner',  -- banner | social_post | social_carousel
  add column if not exists research_topic text,
  add column if not exists research_notes text,
  add column if not exists carousel_slide_count int not null default 1;

-- ============================================================
-- 2. Creatives: slide_index for carousels
-- ============================================================

alter table creatives
  add column if not exists slide_index int not null default 0;
create index if not exists creatives_slide_idx on creatives(campaign_id, slide_index);

-- ============================================================
-- 3. Personas library: add UNIQUE on name so ON CONFLICT works
-- ============================================================

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'personas_library_name_unique'
  ) then
    alter table personas_library add constraint personas_library_name_unique unique (name);
  end if;
end$$;

-- ============================================================
-- 4. Indian-market personas — broad coverage across ages, cities, contexts
-- ============================================================

insert into personas_library (name, age_range, income_tier, lifestyle, preferred_imagery, tags) values
  ('Tier 1 Metro Millennial Professional', '28-38', 'middle-high',
   'Bangalore/Mumbai/Delhi tech worker, runs marathons, weekend brunches, tracks investments, uses Cred/Zerodha',
   'modern interiors, café shots, athleisure, sleek device mockups',
   '{india,tier1,career,fintech}'),

  ('Tier 2 City Aspirational Shopper', '24-35', 'middle',
   'Pune/Jaipur/Indore middle-class, balances tradition and trend, value-conscious but brand-aware, weekend mall outings',
   'bright local-context shots, family settings, mid-priced products',
   '{india,tier2,aspirational}'),

  ('Tier 3 First-Time Online Buyer', '22-40', 'low-middle',
   'Smaller-town India, recently moved online for shopping, prefers COD, trusts Hindi/regional language',
   'simple high-contrast graphics, vernacular cues, family approval',
   '{india,tier3,first-time}'),

  ('Indian Gen Z Students', '17-24', 'low-middle',
   'College students across India, value-led, social-media native, follow desi creators, exam-driven',
   'bold colours, campus settings, smartphones, hostel/PG vibes',
   '{india,genz,student,social}'),

  ('Working Women 25-35 (India)', '25-35', 'middle-high',
   'Career-focused urban Indian women, balance work + self-care, beauty + wellness conscious',
   'modern workspaces, café meetings, wellness studios, soft warm tones',
   '{india,women,career,wellness}'),

  ('Working Mothers 35-50 (India)', '35-50', 'middle-high',
   'Juggling career and family, time-poor, looks for convenience, premium-when-justified',
   'warm home scenes, hands-on kitchen, school-pickup moments, calm palettes',
   '{india,women,family,convenience}'),

  ('Indian Millennial Dads', '30-42', 'middle-high',
   'Married with young kids, weekend road trips, gadget enthusiast, family-financial planning mindset',
   'family scenes, SUVs, weekend outings, dad-tech shots',
   '{india,family,career,tech}'),

  ('Retired NRIs / Senior Citizens', '55-72', 'middle-high',
   'NRI returnees or Indian retirees, health-focused, religious or spiritual, family-anchored, conservative spenders',
   'serene tones, traditional motifs, wellness/spiritual contexts, family settings',
   '{india,senior,wellness,traditional}'),

  ('Indian SMB Owner', '32-55', 'middle-high',
   'Runs a 5–50 person business, time-poor, GST/UPI/HR pain points, values reliability',
   'office/shop interiors, computer screens with dashboards, handshake moments, neutral palettes',
   '{india,b2b,smb,career}'),

  ('Indian IT Professional', '25-40', 'middle-high',
   'Tech worker, in-office or hybrid, gym + gadgets + game streaming, salary-account savvy',
   'modern offices, multi-monitor setups, athleisure, dark-mode UI',
   '{india,tech,career}'),

  ('Wedding & Big-Life Moments', '24-35', 'middle-high',
   'Indian weddings, baby showers, anniversaries — high-spend lifecycle moments, plans 3-9 months ahead',
   'rich tones, traditional fabrics, candlelight, festive context',
   '{india,wedding,family,big-spend}'),

  ('Indian Fitness Aspirants', '22-38', 'middle',
   'Gym beginners and intermediate, supplements + activewear + tracking apps, value transformation stories',
   'gym interiors, athleisure, supplements, water bottles, India-specific gym chains',
   '{india,fitness,wellness}'),

  ('Indian Foodies', '23-40', 'middle-high',
   'Restaurant explorers, regional cuisine enthusiasts, food-photography aware, Zomato/Swiggy power users',
   'plated dishes, casual cafés, biryani/regional thalis, warm interiors',
   '{india,food,lifestyle}'),

  ('Indian Weekend Travellers', '25-45', 'middle-high',
   'Short trips to Goa/Coorg/Manali, hotel bookers, Instagram-conscious, budget-aware',
   'mountains, beaches, boutique hotels, luggage on cars, candid travel',
   '{india,travel,leisure}'),

  ('Indian Beauty Buyers', '20-38', 'middle-high',
   'Skincare-first, brand-loyal once converted, watches creators, willing to try Korean/desi indie brands',
   'mirror selfies, vanity flat-lays, soft pinks/peach palette, indie packaging',
   '{india,beauty,women,wellness}'),

  ('Indian Gamers / Streamers', '18-30', 'middle',
   'PC/mobile gaming, Free Fire/BGMI culture, late-night sessions, peripheral upgrades, Discord regulars',
   'RGB setups, dark mood, gaming peripherals, dramatic lighting',
   '{india,gaming,tech,genz}'),

  ('Govt / PSU Employees', '32-55', 'middle',
   'Stable income, family-anchored, conservative on spending, looks for tax-saving + insurance',
   'modest interiors, family scenes, formal Indian wear, calm composition',
   '{india,tier2,family,traditional}'),

  ('Indian Parents with Young Kids', '28-42', 'middle-high',
   'Kids 2-10, time-poor, education and safety conscious, balances treats with frugality',
   'kid-friendly meals, school scenes, soft warm tones, hands-on parenting',
   '{india,family,parenting}'),

  ('Tier 1 Affluent Established', '38-55', 'high',
   'Established professionals or business owners, premium brands, international travel, wealth-management aware',
   'boutique hotels, premium cars, gallery interiors, golden-hour lighting',
   '{india,premium,wealth}'),

  ('Indian College Aspirants & Parents', '17-22 / 40-55', 'middle',
   'JEE/NEET/UPSC prep candidates and their parents — high-stakes spending on coaching, books, tech',
   'study desks with laptops, books stacked, parental pride moments, exam halls',
   '{india,education,family}')
on conflict (name) do nothing;
