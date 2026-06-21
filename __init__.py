# -*- coding: utf-8 -*-
def classFactory(iface):
    from .segtree import PluginMain
    return PluginMain(iface)