-- Layer: integrity. uuid_v7, triggers, constraints (spec 5.2, 8).
begin;
select * from no_plan();

-- app.uuid_v7 (spec 5.2): compatibility, ordering, uniqueness
create temp table gen as select n, app.uuid_v7() as u from generate_series(1, 10000) as n;
select is((select count(*) from gen where substr(u::text, 15, 1) <> '7'), 0::bigint, 'uuid_v7: version nibble is 7');
select is((select count(*) from gen where substr(u::text, 20, 1) not in ('8', '9', 'a', 'b')), 0::bigint, 'uuid_v7: RFC variant bits');
select is((select count(distinct u) from gen), 10000::bigint, 'uuid_v7: unique over 10,000 values');
select is((select count(*) from (select u < lag(u) over (order by n) as inv from gen) s where inv), 0::bigint, 'uuid_v7: no ordering inversions in one statement');
select ok(abs(extract(epoch from now()) - extract(epoch from to_timestamp(('x' || substr(replace((select u::text from gen where n = 1), '-', ''), 1, 12))::bit(48)::bigint / 1000.0))) < 10, 'uuid_v7: embedded timestamp matches the clock');
select is(substr(replace(app.uuid_v7('2026-01-01 00:00:00+00'::timestamptz)::text, '-', ''), 1, 12), lpad(to_hex((extract(epoch from '2026-01-01 00:00:00+00'::timestamptz) * 1000)::bigint), 12, '0'), 'uuid_v7: explicit timestamp argument is honoured');
select ok(obj_description('app.uuid_v7(timestamptz)'::regprocedure, 'pg_proc') like '%PostgreSQL License%', 'uuid_v7: license is recorded on the function');

select * from finish();
rollback;
