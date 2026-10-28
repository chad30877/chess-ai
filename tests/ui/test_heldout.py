import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
from pathlib import Path
from unittest.mock import patch
import shutil
import unittest
import pygame
from apps.chess_application import ChessApplication, APP_SIZE
from engine.learning.final_comparison import freeze_final_comparison
from engine.learning.labeling import load_labeled_dataset
from tests.helpers.executors import ManualExecutor
from tests.test_learned_comparison import candidate
import tests.test_weight_training as fixtures


class HeldoutUiTest(unittest.TestCase):
    setUp = fixtures.TrainingFlowTest.setUp
    def test_reopen_frozen_report_without_changing_candidate(self):
        labels = self.root/'data/learning/new/teacher-labels/label'
        shutil.copytree(self.labels, labels)
        labeled = load_labeled_dataset(labels)
        source = candidate()
        source.update(dataset_identity=labeled['snapshot']['dataset_sha256'], label_identity=labeled['snapshot']['identity'],
                      label_path=str(labels), calibration={'scale': .01, 'healthy': True, 'identity':'scale-one'})
        final = freeze_final_comparison(self.root, [source])
        pygame.init(); self.addCleanup(pygame.quit)
        with patch('apps.chess_application.PROJECT_ROOT',self.root):
            app=ChessApplication(pygame.display.set_mode(APP_SIZE),executor=ManualExecutor())
            app.mode='learning'; app.learning.page='screening'
            app.learning.screening.open(source, 'test-source')
            app.learning.screening.final_path=final
            def click(action):
                app.render(); b=next(x for x in app.buttons if x.action==action)
                self.assertTrue(b.enabled); app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=b.rect.center,button=1))
            click('learning_screening_heldout')
            click('learning_heldout_freeze'); path=app.learning.heldout.path
            before=(final/'snapshot.json').read_bytes()
            click('learning_heldout_run')
            self.assertFalse(app.learning.heldout.state['report']['independent'])
            app.learning.heldout.open(final)
            self.assertEqual(app.learning.heldout.path,path)
            self.assertEqual((final/'snapshot.json').read_bytes(),before)
            app.close()
