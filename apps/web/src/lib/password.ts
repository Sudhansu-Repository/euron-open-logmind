/**
 * The API's password rule (core/security.py `password_problems`): at least 10 characters,
 * upper and lower case letters, and a digit. Checked here first so the form says exactly
 * what is missing before a round trip.
 */
export function passwordProblems(password: string): string[] {
  const problems: string[] = [];
  if (password.length < 10) problems.push("at least 10 characters");
  if (password.toLowerCase() === password || password.toUpperCase() === password)
    problems.push("upper and lower case letters");
  if (!/\d/.test(password)) problems.push("a digit");
  return problems;
}

export function passwordMessage(password: string): string | null {
  const p = passwordProblems(password);
  return p.length ? `Password needs ${p.join(", ")}.` : null;
}
