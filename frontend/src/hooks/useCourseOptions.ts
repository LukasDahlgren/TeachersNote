import { useEffect, useState } from "react";

import { getProfileCourseOptions } from "../api";
import type { Course } from "../types";

export function useCourseOptions(): Course[] {
  const [courses, setCourses] = useState<Course[]>([]);

  useEffect(() => {
    getProfileCourseOptions()
      .then((options) => setCourses(options.all_courses ?? []))
      .catch(() => {});
  }, []);

  return courses;
}
