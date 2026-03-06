import { describe, expect, it } from "vitest";

import { formatLectureDisplayName, splitLectureName } from "../utils/lectureNaming";

describe("lectureNaming", () => {
  it("formats course display names without changing equivalent codes", () => {
    expect(formatLectureDisplayName({
      name: "DA1234-lecture-5-2026",
      course_id: "DA1234",
      course_display: "DA1234",
    })).toBe("DA1234-lecture-5-2026");

    expect(formatLectureDisplayName({
      name: "DA1234-lecture-5-2026",
      course_id: "DA1234",
      course_display: "Data Engineering",
    })).toBe("Data Engineering-lecture-5-2026");
  });

  it("splits lecture names into display parts without changing fallback behavior", () => {
    expect(splitLectureName("DA1234-lecture-5-2026.pdf")).toEqual({
      courseId: "DA1234",
      displayName: "lecture 5",
      kind: "",
      lectureLabel: "lecture-5-2026",
      number: "2026",
    });

    expect(splitLectureName("")).toEqual({
      courseId: "Lecture",
      displayName: "Lecture",
      kind: "",
      lectureLabel: "Lecture",
      number: "",
    });
  });
});
