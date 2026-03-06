import { describe, expect, it } from "vitest";

import { formatLectureDisplayName, splitLectureName } from "./lectureNaming";

describe("lectureNaming", () => {
  it("replaces the course id prefix with the display code", () => {
    expect(formatLectureDisplayName({
      name: "DA1000-lecture-3-2026",
      course_id: "DA1000",
      course_display: "DA1000V",
    })).toBe("DA1000V-lecture-3-2026");
  });

  it("keeps the original name when the normalized course ids match", () => {
    expect(formatLectureDisplayName({
      name: "DA1000-lecture-3-2026",
      course_id: "DA1000",
      course_display: "da 1000",
    })).toBe("DA1000-lecture-3-2026");
  });

  it("splits a filename-style lecture name into display parts", () => {
    expect(splitLectureName("DA1000-lecture-12-2026.pdf")).toEqual({
      courseId: "DA1000",
      lectureLabel: "lecture-12-2026",
      displayName: "lecture 12",
      kind: "",
      number: "2026",
    });
  });
});
