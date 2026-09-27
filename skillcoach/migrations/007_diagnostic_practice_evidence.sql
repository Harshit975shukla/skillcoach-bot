-- Backfill only completed five-answer diagnostics whose submission and confirmed delivery
-- bound completion to the same IST date. Ambiguous cross-date cases are left untouched.
WITH evidence AS (
    SELECT c.learner_id, min(o.delivered_at) AS delivered,
           min(j.created_at) AS submitted
    FROM coach_state c
    JOIN answer_keys a ON a.learner_id=c.learner_id
        AND a.session_id=c.body->'journey'->>'id' AND a.question_id='diagnostic-4'
    JOIN jobs j ON j.id=a.job_id AND j.status='done'
    JOIN ai_results r ON r.job_id=j.id AND r.operation='journey-rating'
    JOIN outbox o ON o.job_id=j.id AND o.status='sent' AND o.delivered_at IS NOT NULL
        AND o.body->>'kind'='text' AND o.body->>'text' LIKE 'Your five diagnostic answers are saved.%'
        AND NOT coalesce((o.body->>'recovery_notice')::boolean,false)
    WHERE jsonb_array_length(c.body->'journey'->'diagnostic_answers')=5
      AND c.body->'journey'->'diagnostic_rating' = r.body
      AND (SELECT count(*) FROM answer_keys k WHERE k.learner_id=c.learner_id
           AND k.session_id=a.session_id AND k.question_id IN
           ('diagnostic-0','diagnostic-1','diagnostic-2','diagnostic-3','diagnostic-4'))=5
    GROUP BY c.learner_id
), proven AS (
    SELECT learner_id,(delivered AT TIME ZONE 'Asia/Kolkata')::date::text AS practice_date
    FROM evidence WHERE (submitted AT TIME ZONE 'Asia/Kolkata')::date =
                        (delivered AT TIME ZONE 'Asia/Kolkata')::date
)
UPDATE coach_state c SET body =
    jsonb_set(jsonb_set(c.body,'{journey,diagnostic_practice_date}',to_jsonb(p.practice_date)),
              '{activity}',CASE WHEN coalesce(c.body->'activity','[]'::jsonb) ? p.practice_date
              THEN c.body->'activity'
              ELSE coalesce(c.body->'activity','[]'::jsonb) || jsonb_build_array(p.practice_date) END),
    revision=revision+1
FROM proven p WHERE c.learner_id=p.learner_id
    AND c.body->'journey'->>'diagnostic_practice_date' IS NULL;

INSERT INTO schema_migrations(version) VALUES (7);
