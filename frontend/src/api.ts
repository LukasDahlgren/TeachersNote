export { ApiError, buildAssetUrl, clearStoredToken, getStoredToken } from "./api/client";
export { getMe, login, logout, register } from "./api/auth";
export { type ChatMessage, chatWithLecture } from "./api/chat";
export {
  archiveLecture,
  checkHealth,
  type DemoLectureSelection,
  findBestLectureWithNotesByExactName,
  getDeletedLectures,
  getDemoLecture,
  getLecture,
  getLectures,
  getMyLectures,
  processFiles,
  restoreLecture,
  saveLecture,
  trashLecture,
  unarchiveLecture,
  unsaveLecture,
} from "./api/lectures";
export {
  getProcessJob,
  getRegenerateNotesJob,
  regenerateLectureNotes,
  startProcessJob,
  startRegenerateNotesJob,
  subscribeProcessJobEvents,
  subscribeRegenerateNotesEvents,
} from "./api/jobs";
export {
  getProfile,
  getProfileCourseOptions,
  getPublicPrograms,
  updateProfileCourses,
  updateProfileProgram,
} from "./api/profile";
export {
  approveLecture,
  createCourse,
  createProgram,
  getCourses,
  getPendingLectures,
  getProgramCourses,
  getProgramPlan,
  getPrograms,
  mapProgramCourse,
  type ProgramCoursesResponse,
  rejectLecture,
  runCatalogSync,
  unmapProgramCourse,
  updateCourse,
  updateProgram,
} from "./api/admin";
