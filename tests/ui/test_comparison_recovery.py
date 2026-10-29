"""比較工作關閉恢復與跨頁來源保護。"""
import os
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from tests.helpers.executors import ManualExecutor
from tests.test_learned_comparison import candidate
from engine.learning.comparison import create_comparison, comparison_options, comparison_report
from engine.learning.teacher import digest
from engine.storage.batch_storage import write_json_atomic

class ComparisonRecoveryTest(unittest.TestCase):
    def test_close_reopen_bundle_resumes_all_remaining_sources(self):
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            lines=[dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1',moves_uci=[],name='短局',source={})]
            sources=[candidate(),candidate()]; sources[1]['experiment_id']='second'
            plans=[create_comparison(folder, source, roles=('learned',), opening_lines=lines, max_plies=1, screening=True) for source in sources]
            states=[]
            run_evaluation_comparison(**comparison_options(plans[0], 'stable'),progress=states.append,control=lambda:not states or states[-1]['saved_games']<1)
            import json
            replays = {p: p.read_bytes() for p in comparison_report(plans[0])['baselines']['stable']['replays']
                       if json.loads(p.read_text(encoding='utf8'))['metadata']['termination'] != 'user_stop'}
            self.assertTrue(replays)
            bundle=Path(folder)/'data/learning-setup/group'; bundle.mkdir(parents=True)
            data=dict(format_version=1,purpose='screening',sources=sources,work=[dict(path=str(p),baseline='stable') for p in plans],planned_games=4)
            data['identity']=digest(data); write_json_atomic(bundle/'snapshot.json',data)
            snapshots={p:(p/'snapshot.json').read_bytes() for p in plans}
            broken=bundle.parent/'broken'; broken.mkdir(); (broken/'snapshot.json').write_text('{',encoding='utf8')
            executor=ManualExecutor(); app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor); app.new_setup('learning')
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action); self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            app.learning.recovery_future.result(timeout=30); app.render(); click('learning_recovery_list')
            self.assertFalse(any(item['path'] in plans for item in app.learning.recovery_entries))
            self.assertTrue(any(item['path']==broken and item['status']=='unavailable' for item in app.learning.recovery_entries))
            index=next(i for i,item in enumerate(app.learning.recovery_entries) if item['path']==bundle)
            click('learning_recovery_open:'+str(index)); executor.finish(); app.render()
            self.assertEqual(app.learning.page,'history_bundle')
            self.assertIsNone(app.batch)
            click('learning_bundle_resume'); run=app.batch
            app.handle_event(pygame.event.Event(pygame.QUIT)); click('confirm')
            executor.finish(next(i for i,job in enumerate(executor.jobs) if job[0] is run.future)); app.tick(); self.assertFalse(app.running)
            app.close(); app=ChessApplication(app.screen,executor=executor); app.new_setup('learning')
            app.learning.recovery_future.result(timeout=30); app.render(); click('learning_recovery_list')
            index=next(i for i,item in enumerate(app.learning.recovery_entries) if item['path']==bundle)
            click('learning_recovery_open:'+str(index)); executor.finish(); app.render(); click('learning_bundle_resume')
            executor.finish(); self.assertEqual(app.batch.snapshot()['status'],'completed')
            self.assertTrue(all(comparison_report(p)['baselines']['stable']['status']=='completed' for p in plans))
            self.assertTrue(all((p/'snapshot.json').read_bytes()==snapshots[p] for p in plans))
            self.assertTrue(all(p.read_bytes()==content for p,content in replays.items()))
            from ui.unfinished_tasks import unfinished
            self.assertFalse(any(item['path']==bundle for item in unfinished(Path(folder)/'data/learning', folder)))
            app.close()
    def test_running_single_comparison_keeps_original_source_when_browsing_another(self):
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            source_a=candidate(); source_b=candidate(); source_b['experiment_id']='other'
            plan_a=create_comparison(folder,source_a,stable=True); plan_b=create_comparison(folder,source_b)
            executor=ManualExecutor(); app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor); self.addCleanup(app.close)
            app.new_setup('learning'); app.learning.comparison.open_plan(plan_a); app.learning.page='comparison'
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action); self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
            click('learning_compare_start'); run=app.batch
            click('learning_comparison_return'); click('learning_compare_baseline:stable')
            click('learning_nav_inventory'); executor.finish(); app.render()
            click('learning_inventory_history'); executor.finish(); app.render()
            index=next(i for i,item in enumerate(app.learning.comparison_history.entries) if item['path']==plan_b)
            click('learning_history_open:'+str(index)); executor.finish(); app.render()
            self.assertEqual(app.learning.comparison.path,plan_b)
            click('learning_task_return'); self.assertEqual(app.mode,'auto'); self.assertIs(app.batch,run)
            click('learning_comparison_return'); app.render()
            self.assertEqual(app.learning.comparison.path,plan_a)
            self.assertEqual(app.learning.comparison.source,source_a)
            self.assertEqual(app.learning.comparison.baseline,'material')
            run.stop(); executor.finish()
    def test_bundle_replay_preserves_running_bundle_return(self):
        from engine.sessions.evaluation_comparison import run_evaluation_comparison
        pygame.init(); self.addCleanup(pygame.quit)
        with tempfile.TemporaryDirectory() as folder, patch('apps.chess_application.PROJECT_ROOT', Path(folder)):
            lines=[dict(initial_fen='7k/8/8/8/8/8/P7/K7 w - - 0 1',moves_uci=[],name='短局',source={})]
            sources=[candidate(),candidate()]; sources[1]['experiment_id']='second'
            plans=[create_comparison(folder,source,roles=('learned',),opening_lines=lines,max_plies=1,screening=True) for source in sources]
            run_evaluation_comparison(**comparison_options(plans[0],'stable'))
            bundle=Path(folder)/'data/learning-setup/group'; bundle.mkdir(parents=True)
            data=dict(format_version=1,purpose='screening',sources=sources,work=[dict(path=str(p),baseline='stable') for p in plans],planned_games=4)
            data['identity']=digest(data); write_json_atomic(bundle/'snapshot.json',data)
            executor=ManualExecutor(); app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=executor); self.addCleanup(app.close)
            app.new_setup('learning')
            def click(action):
                app.render(); button=next(b for b in app.buttons if b.action==action); self.assertTrue(button.enabled,action)
                app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=button.rect.center,button=1))
                if app.learning.page_loading is not None: executor.finish(); app.render()
            click('learning_goal_compare'); click('learning_inventory_history')
            index=next(i for i,item in enumerate(app.learning.comparison_history.entries) if item['path']==bundle)
            click('learning_history_open:'+str(index)); click('learning_bundle_resume'); run=app.batch
            click('learning_comparison_return'); click('learning_bundle_open:0')
            self.assertEqual(app.learning.comparison.path,plans[0]); click('learning_compare_replay')
            self.assertEqual(app.mode,'replay'); click('learning_comparison_return')
            self.assertEqual(app.learning.comparison.path,plans[0]); click('learning_task_return')
            self.assertIs(app.batch,run); click('learning_comparison_return')
            self.assertEqual(app.learning.page,'history_bundle'); self.assertEqual(app.learning.history_bundle.path,bundle)
            run.stop(); executor.finish(next(i for i,job in enumerate(executor.jobs) if job[0] is run.future))
