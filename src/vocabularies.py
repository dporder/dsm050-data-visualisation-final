"""Record the category frameworks considered for the evaluation.

Sources are given beside each list. The executed options are preserved in
data/processed/alignment/evaluation_tasks.json. Kind used the adapted dictionary
families in that snapshot, rather than the complete Play category list below."""

# Google Play Console app categories (32) as published by Google. App-store mining research uses the
# vendor schemes themselves as ground truth rather than any academic taxonomy (Martin, Sarro, Jia,
# Zhang and Harman 2017, IEEE Transactions on Software Engineering, doi 10.1109/TSE.2016.2630689,
# about 590 citations). No peer-reviewed Play to Apple mapping exists. Checked 2026-09-10:
# https://support.google.com/googleplay/android-developer/answer/9859673
# Games are a separate branch of 17 categories on Play. Collapsed to one label here
# because a two-word name rarely reveals the sub-genre.
GOOGLE_PLAY_APP_CATEGORIES = [
    "Art and Design", "Auto and Vehicles", "Beauty", "Books and Reference", "Business",
    "Comics", "Communications", "Dating", "Education", "Entertainment", "Events", "Finance",
    "Food and Drink", "Health and Fitness", "House and Home", "Libraries and Demo", "Lifestyle",
    "Maps and Navigation", "Medical", "Music and Audio", "News and Magazines", "Parenting",
    "Personalization", "Photography", "Productivity", "Shopping", "Social", "Sports", "Tools",
    "Travel and Local", "Video Players and Editors", "Weather",
]
KIND_OPTIONS = GOOGLE_PLAY_APP_CATEGORIES + ["Games (any game category)", "Cannot tell from the name"]

# Audience. Perplexity's review (13 September 2026) found NO dominant closed typology for whom
# software is made. It recommended von Hippel's household-sector versus producer-sector split
# (free innovation: developed by consumers at private cost, in unpaid time, not protected, often
# given away. Von Hippel, de Jong and Flowers 2012, Management Science, doi 10.1287/mnsc.1110.1508;
# von Hippel 2017, Free Innovation, MIT Press) as the cited axis, with app-store monetisation
# typologies (Martin et al. 2017) as a second axis that a bare name cannot reveal and is left to the
# fall study. Household sector covers the maker, their family, friends, club or community, unpaid.
AUDIENCE_OPTIONS = [
    "Household sector: for the maker, their family, friends or a community, unpaid",
    "Producer sector: for a business, clients or paying customers",
    "Cannot tell from the name",
]

# Maker type: the end-user programming canon's three-way distinction, end user, end-user programmer,
# professional programmer (Nardi 1993. Ko et al. 2011, ACM Computing Surveys, doi 10.1145/1922649.1922658;
# Scaffidi, Shaw and Myers 2005), confirmed by Perplexity as the most defensible closed set. The model's answer is one
# term in a weighted score with the deterministic footprint signals (HANDOFF D16).
MAKER_OPTIONS = [
    "Looks made by a professional developer",
    "Looks made by someone technical but not a professional developer",
    "Looks made by a non-programmer",
    "Cannot tell from the evidence",
]

# Name style: the trademark distinctiveness spectrum (Abercrombie & Fitch Co. V. Hunting World,
# Inc., 537 F.2d 4, 2d Cir. 1976), confirmed by Perplexity as the standard classification of how
# much a name describes the thing named. Precedent for our exact method: 'Automating Abercrombie'
# (Journal of Empirical Legal Studies, 2024, doi 10.1111/jels.12398) aligned a classifier to human
# labels on technology brand names.
NAMESTYLE_OPTIONS = [
    "Generic (names the thing itself: 'tracker', 'shop')",
    "Descriptive (says what it does: 'habit-tracker')",
    "Suggestive (hints at the purpose: 'golden-hour-hairdresser')",
    "Arbitrary (a real word unrelated to the purpose: 'aurora')",
    "Fanciful (an invented word: 'vibescudo')",
    "Cannot tell",
]
