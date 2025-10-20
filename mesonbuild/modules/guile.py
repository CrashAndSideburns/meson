# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 The Meson development team

from __future__ import annotations

import copy
from shutil import copymode
import typing as T

from mesonbuild import mesonlib, mlog
from mesonbuild.build import Executable
from mesonbuild.dependencies.base import ExternalLibrary
from mesonbuild.dependencies.detect import find_external_dependency
from mesonbuild.dependencies.pkgconfig import PkgConfigDependency
from mesonbuild.interpreter.interpreterobjects import extract_required_kwarg
from mesonbuild.interpreterbase.decorators import ContainerTypeInfo, FeatureNew
from mesonbuild.utils.core import HoldableObject
from mesonbuild.utils.universal import MachineChoice

from . import NewExtensionModule, ModuleInfo
from ..options import UserFeatureOption
from ..interpreterbase import (
    typed_pos_args, typed_kwargs, KwargInfo, disablerIfNotFound
)
from ..programs import ExternalProgram, NonExistingExternalProgram

if T.TYPE_CHECKING:
    from . import ModuleState
    from ..interpreter import Interpreter
    from ..interpreter.kwargs import ExtractRequired

    class FindInstallationKw(ExtractRequired):

        disabler: bool
        modules: T.List[str]
        pure: T.Optional[bool]

    MaybeGuildProg = T.Union[NonExistingExternalProgram, 'GuildExternalProgram']
    MaybeGuileProg = T.Union[NonExistingExternalProgram, 'GuileExternalProgram']
    MaybeGuileInstallation = T.Union[None, 'GuileInstallation']

class GuildExternalProgram(ExternalProgram):
    pass

class GuileExternalProgram(ExternalProgram):

    def wrap_method(self, args: T.Tuple[str]) -> 'Executable':
      pass

class GuileInstallation(HoldableObject):
    def __init__(self, guile: 'GuileExternalProgram', guild: 'GuildExternalProgram') -> None:
        self.guile = guile
        self.guild = guild

class GuileModule(NewExtensionModule):

    INFO = ModuleInfo('guile', '')

    def __init__(self) -> None:
        super().__init__()
        self.installations: T.Dict[str, MaybeGuileProg] = {}
        self.methods.update({
            'find_installation': self.find_installation,
        })

    @disablerIfNotFound
    @typed_pos_args('python.find_installation', str)
    @typed_kwargs(
        'python.find_installation',
        KwargInfo('required', (bool, UserFeatureOption), default=True),
        KwargInfo('disabler', bool, default=False),
        KwargInfo('modules', ContainerTypeInfo(list, str), listify=True, default = []),
    )
    def find_installation(self, state: 'ModuleState', args: T.Tuple[str],
                          kwargs: 'FindInstallationKw') -> MaybeGuileInstallation:
        feature_check = FeatureNew('Passing "feature" option to find_installation', '')
        disabled, required, feature = extract_required_kwarg(kwargs, state.subproject, feature_check)

        # pkg-config is the canonical method by which guile manages multiple parallel installations
        libguile = PkgConfigDependency(args[0], state.environment, {})

        if not libguile.found():
            if required:
                raise mesonlib.MesonException('{} not found'.format(args[0]))
            return None

        # once the desired version of libguile is located, it contains pkg-config variables pointing to the executables
        # for `guile` (the interpreter) and `guild` (the bytecode compiler)
        guile = GuileExternalProgram('guile', command = [libguile.get_variable(pkgconfig = 'guile')], silent = True)
        guild = GuildExternalProgram('guild', command = [libguile.get_variable(pkgconfig = 'guild')])

        want_modules = kwargs['modules']
        found_modules: T.List[str] = []
        missing_modules: T.List[str] = []
        if guile.found() and want_modules:
            for mod in want_modules:
                p, *_ = mesonlib.Popen_safe(
                    guile.command +
                    ['-c', f'(use-modules ({mod}))'])
                if p.returncode != 0:
                    missing_modules.append(mod)
                else:
                    found_modules.append(mod)

        msg: T.List['mlog.TV_Loggable'] = ['Program', mlog.bold(guile.name)]
        if want_modules:
            msg.append('({})'.format(', '.join(want_modules)))
        msg.append('found:')
        if guile.found() and not missing_modules:
            msg.extend([mlog.green('YES'), '({})'.format(' '.join(guile.command))])
        else:
            msg.append(mlog.red('NO'))
        if found_modules:
            msg.append('modules:')
            msg.append(', '.join(found_modules))

        mlog.log(*msg)

        if not guile.found():
            if required:
                raise mesonlib.MesonException('{} not found'.format(guile.name))
            return None
        elif missing_modules:
            if required:
                raise mesonlib.MesonException('{} is missing modules: {}'.format(guile.name, ', '.join(missing_modules)))
            return None
        elif not guild.found():
            if required:
                raise mesonlib.MesonException('{} not found'.format(guild.name))
        else:
            return GuileInstallation(guile, guild)

def initialize(interpreter: 'Interpreter') -> GuileModule:
    interpreter.append_holder_map(HoldableObject, GuileInstallation)
    return GuileModule()
