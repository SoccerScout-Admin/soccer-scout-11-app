/**
 * playerDemographics
 * -------------------
 * Pure helpers for derived roster analytics. Nothing here touches the
 * network — these are formatters/parsers used by hero chips, filter
 * dropdowns, and dossier badges.
 *
 * `ageGroupLabel` follows U-system soccer convention: U-N means "under N",
 * so a 15-year-old is U16. This matches how clubs name age groups (U14,
 * U17, etc.) instead of raw age.
 *
 * `classOfLabel` is best-effort: we parse the grade string and assume
 * the player graduates at the end of the *current school year* for
 * seniors, etc. Northern-hemisphere academic calendar (Aug → May).
 */

const _currentYear = new Date().getFullYear();
const _currentMonth = new Date().getMonth() + 1; // 1-12

// School year ends in June. If it's July onward, we're in the "new" school year.
const _schoolYearEnd = _currentMonth >= 7 ? _currentYear + 1 : _currentYear;

// Map grade text -> years until graduation (HS graduation in the U.S. system).
// "12th (Senior)" graduates THIS school year, "11th (Junior)" next year, etc.
const _yearsToGrad = {
  '6th': 7,
  '7th': 6,
  '8th': 5,
  '9th (freshman)': 4,
  '10th (sophomore)': 3,
  '11th (junior)': 2,
  '12th (senior)': 1,
  // College → "Class of" still meaningful (year of expected bachelor's).
  'college freshman': 4,
  'college sophomore': 3,
  'college junior': 2,
  'college senior': 1,
  'graduate / post-grad': 0,
};

export const ageFromBirthYear = (birthYear) => {
  const y = parseInt(birthYear, 10);
  if (!y || y <= 0) return null;
  return _currentYear - y;
};

/**
 * U-system age group label. A player aged 13 → "U14".
 * Returns null if birth_year is missing/invalid.
 */
export const ageGroupLabel = (birthYear) => {
  const age = ageFromBirthYear(birthYear);
  if (age === null || age < 0) return null;
  return `U${age + 1}`;
};

/**
 * Best-effort "Class of YYYY" label derived from current_grade.
 * - HS seniors → graduate at the end of current school year
 * - 9th-11th → forward-extrapolate to senior year
 * - College → year of expected bachelor's
 * Returns null if we can't confidently derive a year.
 */
export const classOfLabel = (currentGrade) => {
  if (!currentGrade || typeof currentGrade !== 'string') return null;
  const yrs = _yearsToGrad[currentGrade.trim().toLowerCase()];
  if (yrs === undefined) return null;
  return `Class of ${_schoolYearEnd + (yrs - 1)}`;
};

/**
 * Convenience: array of {key, label} for both badges if available.
 * Used by hero/chip components to render in one place.
 */
export const demographicBadges = (player) => {
  if (!player) return [];
  const out = [];
  const ag = ageGroupLabel(player.birth_year);
  if (ag) out.push({ key: 'age-group', label: ag });
  const co = classOfLabel(player.current_grade);
  if (co) out.push({ key: 'class-of', label: co });
  return out;
};
