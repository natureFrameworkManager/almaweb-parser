-- SQLite
-- ============================================================
-- 1. Courses which share events
--    Two or more courses linked to the same event via CourseEventLink
-- ============================================================
SELECT
    c1.id AS course_a_id,
    c1.name AS course_a,
    c1.number AS course_a_number,
    c2.id AS course_b_id,
    c2.name AS course_b,
    c2.number AS course_b_number,
    e.name AS shared_event_name,
    e.id AS event_id,
    e.event_date AS event_date,
    e.start_time AS event_start_time,
    e.end_time AS event_end_time,
    e.location_id AS event_location_id
FROM courseeventlink cel1
JOIN courseeventlink cel2
    ON cel1.event_id = cel2.event_id
   AND cel1.course_id < cel2.course_id
JOIN course c1 ON c1.id = cel1.course_id
JOIN course c2 ON c2.id = cel2.course_id
JOIN event e   ON e.id   = cel1.event_id
ORDER BY e.id, c1.name;


-- ============================================================
-- 2. Modules which share courses
--    Two or more modules linked to the same course via ModuleCourseLink
-- ============================================================
SELECT
    m1.id AS module_a_id,
    m1.name AS module_a,
    m1.number AS module_a_number,
    m2.id AS module_b_id,
    m2.name AS module_b,
    m2.number AS module_b_number,
    c.name  AS shared_course_name,
    c.id    AS course_id,
    c.number AS course_number
FROM modulecourselink mcl1
JOIN modulecourselink mcl2
    ON mcl1.course_id = mcl2.course_id
   AND mcl1.module_id < mcl2.module_id
JOIN module m1 ON m1.id = mcl1.module_id
JOIN module m2 ON m2.id = mcl2.module_id
JOIN course c  ON c.id  = mcl1.course_id
ORDER BY c.id, m1.name;


-- ============================================================
-- 3. Modules which share events
--    Two or more modules whose courses are linked to the same event.
--    Traversal: Module -> ModuleCourseLink -> Course -> CourseEventLink -> Event
-- ============================================================
SELECT DISTINCT
    m1.id AS module_a_id,
    m1.name AS module_a,
    m1.number AS module_a_number,
    m2.id AS module_b_id,
    m2.name AS module_b,
    m2.number AS module_b_number,
    e.name  AS shared_event_name,
    e.id    AS event_id,
    e.event_date AS event_date,
    e.start_time AS event_start_time,
    e.end_time   AS event_end_time,
    e.location_id AS event_location_id
FROM modulecourselink mcl1
JOIN modulecourselink mcl2
    ON mcl1.course_id = mcl2.course_id
   AND mcl1.module_id < mcl2.module_id
JOIN module m1 ON m1.id = mcl1.module_id
JOIN module m2 ON m2.id = mcl2.module_id
JOIN courseeventlink cel1 ON cel1.course_id = mcl1.course_id
JOIN event e ON e.id = cel1.event_id
ORDER BY e.id, m1.name;