# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members


import datetime
from datetime import timedelta

from parameterized import parameterized

import mock

from twisted.internet import defer
from twisted.trial import unittest

from buildbot.configurators import janitor
from buildbot.configurators.janitor import JANITOR_NAME
from buildbot.configurators.janitor import BuildDataJanitor
from buildbot.configurators.janitor import BuildsJanitor
from buildbot.configurators.janitor import BuildersJanitor
from buildbot.configurators.janitor import JanitorConfigurator
from buildbot.configurators.janitor import LogChunksJanitor
from buildbot.process.results import SUCCESS
from buildbot.schedulers.forcesched import ForceScheduler
from buildbot.schedulers.timed import Nightly
from buildbot.test.reactor import TestReactorMixin
from buildbot.test.steps import TestBuildStepMixin
from buildbot.test.util import config as configmixin
from buildbot.test.util import configurators
from buildbot.util import datetime2epoch
from buildbot.worker.local import LocalWorker


class JanitorConfiguratorTests(configurators.ConfiguratorMixin, unittest.SynchronousTestCase):
    ConfiguratorClass = JanitorConfigurator

    def test_nothing(self):
        self.setupConfigurator()
        self.assertEqual(self.config_dict, {
        })

    @parameterized.expand([
        ('logs', {'logHorizon': timedelta(weeks=1)}, [LogChunksJanitor]),
        ('build_data', {'build_data_horizon': timedelta(weeks=1)}, [BuildDataJanitor]),
        ('logs_build_data', {'build_data_horizon': timedelta(weeks=1),
                             'logHorizon': timedelta(weeks=1)},
         [LogChunksJanitor, BuildDataJanitor]),
        ('horizon_per_builder', {'horizon_per_builder': {
                                'b1': {
                                'logHorizon': timedelta(weeks=1),
                                'buildDataHorizon': timedelta(weeks=1)}}},
         [LogChunksJanitor, BuildDataJanitor]),
    ])
    def test_steps(self, name, configuration, exp_steps):
        self.setupConfigurator(**configuration)
        self.expectWorker(JANITOR_NAME, LocalWorker)
        self.expectScheduler(JANITOR_NAME, Nightly)
        self.expectScheduler(JANITOR_NAME + "_force", ForceScheduler)
        self.expectBuilderHasSteps(JANITOR_NAME, exp_steps)
        self.expectNoConfigError()


class JanitorConfiguratorErrorsTests(TestBuildStepMixin,
                            configmixin.ConfigErrorsMixin,
                            TestReactorMixin,
                            unittest.TestCase):

    def test_BuildDataJanitor_InvalidConfig(self):
        horizon_per_builder = {
            "b1": {
            "logHorizon": timedelta(weeks=1),
            "buildDataHorizon": timedelta(weeks=1)
            }
        }
        with self.assertRaisesConfigError("JanitorConfigurator: horizon_per_builder only " +
                "possible without logHorizon and build_data_horizon set."):
            self.setup_step(JanitorConfigurator(logHorizon=timedelta(weeks=1),
                horizon_per_builder=horizon_per_builder))
            self.setup_step(JanitorConfigurator(build_data_horizon=timedelta(weeks=1),
                horizon_per_builder=horizon_per_builder))


class LogChunksJanitorTests(TestBuildStepMixin,
                            configmixin.ConfigErrorsMixin,
                            TestReactorMixin,
                            unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.setup_test_reactor()
        yield self.setup_test_build_step()
        self.patch(janitor, "now", lambda: datetime.datetime(year=2017, month=1, day=1))

    def tearDown(self):
        return self.tear_down_test_build_step()

    @defer.inlineCallbacks
    def test_basic(self):
        self.setup_step(
            LogChunksJanitor(logHorizon=timedelta(weeks=1)))
        self.master.db.logs.deleteOldLogChunks = mock.Mock(return_value=3)
        self.expect_outcome(result=SUCCESS,
                           state_string="deleted 3 logchunks")
        yield self.run_step()
        expected_timestamp = datetime2epoch(datetime.datetime(year=2016, month=12, day=25))
        self.master.db.logs.deleteOldLogChunks.assert_called_with(
            older_than_timestamp=expected_timestamp)

    @defer.inlineCallbacks
    def test_LogChunksJanitorHorizon_PerBuilder(self):
        config = {
            "b1": {
            "logHorizon": timedelta(weeks=1),
            "buildDataHorizon": timedelta(weeks=1)
            }
        }
        self.setup_step(LogChunksJanitor(horizon_per_builder=config))
        self.master.db.logs.deleteOldLogChunks = mock.Mock(return_value=3)
        self.expect_outcome(result=SUCCESS,
                           state_string="deleted 3 logchunks")
        yield self.run_step()
        self.master.db.logs.deleteOldLogChunks.assert_called_with(
            horizon_per_builder=config)

    @defer.inlineCallbacks
    def test_build_data(self):
        self.setup_step(BuildDataJanitor(build_data_horizon=timedelta(weeks=1)))
        self.master.db.build_data.deleteOldBuildData = mock.Mock(return_value=4)
        self.expect_outcome(result=SUCCESS, state_string="deleted 4 build data key-value pairs")
        yield self.run_step()
        expected_timestamp = datetime2epoch(datetime.datetime(year=2016, month=12, day=25))
        self.master.db.build_data.deleteOldBuildData.assert_called_with(
            older_than_timestamp=expected_timestamp)

    @defer.inlineCallbacks
    def test_BuildDataJanitor_horizon_per_builder(self):
        config = {
            "b1": {
            "logHorizon": timedelta(weeks=1),
            "buildDataHorizon": timedelta(weeks=1)
            }
        }
        self.setup_step(BuildDataJanitor(horizon_per_builder=config))
        self.master.db.build_data.deleteOldBuildData = mock.Mock(return_value=4)
        self.expect_outcome(result=SUCCESS, state_string="deleted 4 build data key-value pairs")
        yield self.run_step()
        self.master.db.build_data.deleteOldBuildData.assert_called_with(
            horizon_per_builder=config)

    @defer.inlineCallbacks
    def test_BuildsJanitor_horizon_per_builder(self):
        config = {
            "b1": {
            "buildsHorizon": timedelta(weeks=1)
            }
        }
        self.setup_step(BuildsJanitor(horizon_per_builder=config))
        self.master.db.builds.deleteOldBuilds = mock.Mock(return_value=3)
        self.expect_outcome(result=SUCCESS, state_string="deleted 3 builds")
        yield self.run_step()
        self.master.db.builds.deleteOldBuilds.assert_called_with(
            horizon_per_builder=config)

    @defer.inlineCallbacks
    def test_BuildersJanitor_horizon_per_builder(self):
        self.setup_step(BuildersJanitor())
        self.master.db.builders.deleteOldBuilders = mock.Mock(return_value=3)
        self.expect_outcome(result=SUCCESS, state_string="deleted 3 builders")
        yield self.run_step()
        self.master.db.builders.deleteOldBuilders.assert_called_with()
