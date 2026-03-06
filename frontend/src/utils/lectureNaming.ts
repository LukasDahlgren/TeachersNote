export interface LectureDisplayInput {
  name?: string;
  course_id?: string | null;
  course_display?: string | null;
}

export interface LectureNameParts {
  courseId: string;
  lectureLabel: string;
  displayName: string;
  kind: string;
  number: string;
}

export function normalizeCourseToken(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function formatLectureDisplayName(input: LectureDisplayInput): string {
  const rawName = input.name ?? "";
  const name = rawName.trim();
  if (!name) return rawName;

  const courseId = (input.course_id ?? "").trim();
  const courseDisplay = (input.course_display ?? "").trim();
  if (!courseId || !courseDisplay) return rawName;
  if (normalizeCourseToken(courseId) === normalizeCourseToken(courseDisplay)) return rawName;

  const prefixPattern = new RegExp(`^${escapeRegex(courseId)}(?=($|[-_\\s]))`, "i");
  if (prefixPattern.test(name)) {
    return name.replace(prefixPattern, courseDisplay);
  }

  const firstToken = name.split(/[-_\s]+/, 1)[0] ?? "";
  if (normalizeCourseToken(firstToken) === normalizeCourseToken(courseId)) {
    return `${courseDisplay}${name.slice(firstToken.length)}`;
  }

  return rawName;
}

export const formatLectureSummaryDisplayName = formatLectureDisplayName;

function stripExtension(value: string): string {
  return value.replace(/\.[^./\\]+$/, "");
}

export function splitLectureName(name: string): LectureNameParts {
  const cleanedName = stripExtension(name).replace(/\s+/g, " ").trim();
  if (!cleanedName) {
    return { courseId: "Lecture", lectureLabel: "Lecture", displayName: "Lecture", kind: "", number: "" };
  }

  const courseId = cleanedName.split(/[-\s_]+/).filter(Boolean)[0] ?? cleanedName;
  let lectureLabel = cleanedName.slice(courseId.length).replace(/^[\s_-]+/, "").trim();
  if (!lectureLabel) lectureLabel = cleanedName;

  const parts = lectureLabel.split(/[-\s_]+/).filter(Boolean);
  let displayName = lectureLabel;
  let kind = "";
  let number = "";

  if (parts.length >= 2) {
    const lastPart = parts[parts.length - 1];
    if (/^\d+$/.test(lastPart)) {
      number = lastPart;
      const potentialKind = parts[parts.length - 2];
      if (/^[a-z]/i.test(potentialKind) && !/^\d+$/.test(potentialKind)) {
        kind = potentialKind;
        displayName = parts.slice(0, parts.length - 2).join(" ");
        if (!displayName) {
          displayName = potentialKind;
          kind = "";
        }
      } else {
        displayName = parts.slice(0, parts.length - 1).join(" ");
      }
    }
  }

  return { courseId, lectureLabel, displayName, kind, number };
}
