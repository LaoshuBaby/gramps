#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2000-2003  Donald N. Allingham
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

"Export to CD (nautilus)"

#-------------------------------------------------------------------------
#
# standard python modules
#
#-------------------------------------------------------------------------
import time
import os
from cStringIO import StringIO

#-------------------------------------------------------------------------
#
# GNOME/GTK modules
#
#-------------------------------------------------------------------------
import gtk
import gtk.glade
import gnome.vfs

#-------------------------------------------------------------------------
#
# GRAMPS modules
#
#-------------------------------------------------------------------------
import WriteXML
import Utils
import const
import QuestionDialog
import RelImage
import ImgManip

from intl import gettext as _

#-------------------------------------------------------------------------
#
# writeData
#
#-------------------------------------------------------------------------
def writeData(database,person):
    try:
        PackageWriter(database)
    except:
        import DisplayTrace
        DisplayTrace.DisplayTrace()
    
#-------------------------------------------------------------------------
#
# PackageWriter
#
#-------------------------------------------------------------------------
class PackageWriter:

    def __init__(self,database):
        self.db = database
        
        base = os.path.dirname(__file__)
        glade_file = "%s/%s" % (base,"cdexport.glade")
        
        
        dic = {
            "destroy_passed_object" : Utils.destroy_passed_object,
            "on_ok_clicked" : self.on_ok_clicked
            }
        
        self.top = gtk.glade.XML(glade_file,"packageExport")

        Utils.set_titles(self.top.get_widget('packageExport'),
                         self.top.get_widget('title'),
                         _('Export to CD'))
        
        self.top.signal_autoconnect(dic)
        self.top.get_widget("packageExport").show()

    def copy_file(self,src,dest):
        original = open(src,"r")
        destobj = gnome.vfs.URI(dest)
        target = gnome.vfs.create(destobj,gnome.vfs.OPEN_WRITE)
        done = 0
        while 1:
            buf = original.read(2048)
            if buf == '':
                break
            else:
                target.write(buf)
        target.close()
        original.close()

    def make_thumbnail(self,dbname,root,path):
        img = ImgManip.ImgManip(path)
        data = img.jpg_scale_data(const.thumbScale,const.thumbScale)
        
        uri = gnome.vfs.URI('burn:///%s/.thumb/%s.jpg' % (dbname,root))
        th = gnome.vfs.create(uri,gnome.vfs.OPEN_WRITE)
        th.write(data)
        th.close()
                       
    def on_ok_clicked(self,obj):
        Utils.destroy_passed_object(obj)

        base = os.path.basename(self.db.getSavePath())

        try:
            uri = gnome.vfs.URI('burn:///%s' % base)
            gnome.vfs.make_directory(uri,gnome.vfs.OPEN_WRITE)
        except gnome.vfs.error, msg:
            print msg

        try:
            uri = gnome.vfs.URI('burn:///%s/.thumb' % base)
            gnome.vfs.make_directory(uri,gnome.vfs.OPEN_WRITE)
        except gnome.vfs.error, msg:
            print msg

        #--------------------------------------------------------
        def remove_clicked():
            # File is lost => remove all references and the object itself
            mobj = self.db.getObject(self.object_id)
            for p in self.db.getFamilyMap().values():
                nl = p.getPhotoList()
                for o in nl:
                    if o.getReference() == mobj:
                        nl.remove(o) 
                p.setPhotoList(nl)
            for key in self.db.getPersonKeys():
                p = self.db.getPerson(key)
                nl = p.getPhotoList()
                for o in nl:
                    if o.getReference() == mobj:
                        nl.remove(o) 
                p.setPhotoList(nl)
            for key in self.db.getSourceKeys():
                p = self.db.getSource(key)
                nl = p.getPhotoList()
                for o in nl:
                    if o.getReference() == mobj:
                        nl.remove(o) 
                p.setPhotoList(nl)
            for key in self.db.getPlaceKeys():
                p = self.db.getPlace(key)
                nl = p.getPhotoList()
                for o in nl:
                    if o.getReference() == mobj:
                        nl.remove(o) 
                p.setPhotoList(nl)
            self.db.removeObject(self.object_id) 
            Utils.modified() 
    
        def leave_clicked():
            # File is lost => do nothing, leave as is
            pass

        def select_clicked():
            # File is lost => select a file to replace the lost one
            def fs_close_window(obj):
                fs_top.destroy()

            def fs_ok_clicked(obj):
                newfile = fs_top.get_filename()
                fs_top.destroy()
                if os.path.isfile(newfile):
                    self.copy_file(newfile,'burn:///%s/%s' % (base,obase))
    	    	    ntype = Utils.get_mime_type(newfile)
		    if ntype[0:5] == "image":
                        self.make_thumbnail(base,obase,newfile)
		    
            fs_top = gtk.FileSelection("%s - GRAMPS" % _("Select file"))
            fs_top.hide_fileop_buttons()
            fs_top.ok_button.connect('clicked',fs_ok_clicked)
            fs_top.cancel_button.connect('clicked',fs_close_window)
            fs_top.show()
            fs_top.run()

        #----------------------------------------------------------

        # Write media files first, since the database may be modified 
        # during the process (i.e. when removing object)

        for obj in self.db.getObjectMap().values():
            oldfile = obj.getPath()
            root = os.path.basename(oldfile)
            if os.path.isfile(oldfile):
                self.copy_file(oldfile,'burn:///%s/%s' % (base,root))
                if obj.getMimeType()[0:5] == "image":
                    self.make_thumbnail(base,root,obj.getPath())
            else:
                # File is lost => ask what to do
                self.object_id = obj.getId()
                QuestionDialog.MissingMediaDialog(_("Media object could not be found"),
	            _("%(file_name)s is referenced in the database, but no longer exists. " 
                        "The file may have been deleted or moved to a different location. " 
                        "You may choose to either remove the reference from the database, " 
                        "keep the reference to the missing file, or select a new file." 
                        ) % { 'file_name' : oldfile },
                    remove_clicked, leave_clicked, select_clicked)


        # Write XML now
        g = gnome.vfs.create('burn:///%s/data.gramps' % base,gnome.vfs.OPEN_WRITE )
        gfile = WriteXML.XmlWriter(self.db,None,1)
        gfile.write_handle(g)
        g.close()
    
#-------------------------------------------------------------------------
#
# Register the plugin
#
#-------------------------------------------------------------------------
from Plugins import register_export

register_export(writeData,_("Export to CD (nautilus)"))
