#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2000-2007  Donald N. Allingham
# Copyright (C) 2008       Brian G. Matherly
# Copyright (C) 2008-2009  Gary Burton
# Copyright (C) 2008       Robert Cheramy <robert@cheramy.net>
# Copyright (C) 2010       Jakim Friant
# Copyright (C) 2010       Nick Hall
# Copyright (C) 2011       Tim G L Lyons
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
# $Id$

"Export to GEDCOM"

#-------------------------------------------------------------------------
#
# Standard Python Modules
#
#-------------------------------------------------------------------------
from gen.ggettext import gettext as _
import os
import time

#-------------------------------------------------------------------------
#
# GRAMPS modules
#
#-------------------------------------------------------------------------
import gen.lib
import const
import libgedcom
import Errors
from ExportOptions import WriterOptionBox
from gen.updatecallback import UpdateCallback
from Utils import media_path_full
from PlaceUtils import conv_lat_lon

#-------------------------------------------------------------------------
#
# GEDCOM tags representing attributes that may take a parameter, value or
# description on the same line as the tag
#
#-------------------------------------------------------------------------
NEEDS_PARAMETER = set(
    ["CAST", "DSCR", "EDUC", "IDNO", "NATI", "NCHI", 
     "NMR",  "OCCU", "PROP", "RELI", "SSN",  "TITL"])

LDS_ORD_NAME = {
    gen.lib.LdsOrd.BAPTISM         : 'BAPL', 
    gen.lib.LdsOrd.ENDOWMENT       : 'ENDL', 
    gen.lib.LdsOrd.SEAL_TO_PARENTS : 'SLGC', 
    gen.lib.LdsOrd.SEAL_TO_SPOUSE  : 'SLGS', 
    gen.lib.LdsOrd.CONFIRMATION    : 'CONL', 
    }

LDS_STATUS = {
    gen.lib.LdsOrd.STATUS_BIC        : "BIC", 
    gen.lib.LdsOrd.STATUS_CANCELED   : "CANCELED", 
    gen.lib.LdsOrd.STATUS_CHILD      : "CHILD", 
    gen.lib.LdsOrd.STATUS_CLEARED    : "CLEARED", 
    gen.lib.LdsOrd.STATUS_COMPLETED  : "COMPLETED", 
    gen.lib.LdsOrd.STATUS_DNS        : "DNS", 
    gen.lib.LdsOrd.STATUS_INFANT     : "INFANT", 
    gen.lib.LdsOrd.STATUS_PRE_1970   : "PRE-1970", 
    gen.lib.LdsOrd.STATUS_QUALIFIED  : "QUALIFIED", 
    gen.lib.LdsOrd.STATUS_DNS_CAN    : "DNS/CAN", 
    gen.lib.LdsOrd.STATUS_STILLBORN  : "STILLBORN", 
    gen.lib.LdsOrd.STATUS_SUBMITTED  : "SUBMITTED" , 
    gen.lib.LdsOrd.STATUS_UNCLEARED  : "UNCLEARED", 
    }

LANGUAGES = {
    'cs' : 'Czech',     'da' : 'Danish',    'nl' : 'Dutch',
    'en' : 'English',   'eo' : 'Esperanto', 'fi' : 'Finnish',
    'fr' : 'French',    'de' : 'German',    'hu' : 'Hungarian',
    'it' : 'Italian',   'lt' : 'Latvian',   'lv' : 'Lithuanian',
    'no' : 'Norwegian', 'po' : 'Polish',    'pt' : 'Portuguese',
    'ro' : 'Romanian',  'sk' : 'Slovak',    'es' : 'Spanish',
    'sv' : 'Swedish',   'ru' : 'Russian',    
    }

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------

MIME2GED = {
    "image/bmp"   : "bmp", 
    "image/gif"   : "gif", 
    "image/jpeg"  : "jpeg", 
    "image/x-pcx" : "pcx", 
    "image/tiff"  : "tiff", 
    "audio/x-wav" : "wav"
    }

QUALITY_MAP = {
    gen.lib.Citation.CONF_VERY_HIGH : "3", 
    gen.lib.Citation.CONF_HIGH      : "2", 
    gen.lib.Citation.CONF_LOW       : "1", 
    gen.lib.Citation.CONF_VERY_LOW  : "0", 
    }

#-------------------------------------------------------------------------
#
# sort_by_gramps_id
#
#-------------------------------------------------------------------------
def sort_by_gramps_id(first, second):
    """
    Sort objects by their Gramps ID.
    """
    return cmp(first.gramps_id, second.gramps_id)

#-------------------------------------------------------------------------
#
# sort_handles_by_id
#
#-------------------------------------------------------------------------
def sort_handles_by_id(handle_list, handle_to_object):
    """
    Sort a list of handles by the Gramps ID. 
    
    The function that returns the object from the handle needs to be supplied 
    so that we get the right object.
    
    """
    sorted_list = []
    for handle in handle_list:
        obj = handle_to_object(handle)
        if obj:
            data = (obj.get_gramps_id(), handle)
            sorted_list.append (data)
    sorted_list.sort()
    return sorted_list

#-------------------------------------------------------------------------
#
# breakup
#
#-------------------------------------------------------------------------
def breakup(txt, limit):
    """
    Break a line of text into a list of strings that conform to the 
    maximum length specified, while breaking words in the middle of a word
    to avoid issues with spaces.
    """
    if limit < 1:
        raise ValueError("breakup: unexpected limit: %r" % limit)
    data = []
    while len(txt) > limit:
        # look for non-space pair to break between
        # do not break within a UTF-8 byte sequence, i. e. first char >127
        idx = limit
        while (idx>0 and (txt[idx-1].isspace() or txt[idx].isspace()
                                               or ord(txt[idx-1]) > 127)):
            idx -= 1
        if idx == 0:
            #no words to break on, just break at limit anyway
            idx = limit
        data.append(txt[:idx])
        txt = txt[idx:]
    if len(txt) > 0:
        data.append(txt)
    return data


#-------------------------------------------------------------------------
#
# event_has_subordinate_data
#   may want to compare description w/ auto-generated one, and
#   if so, treat it same as if it were empty for this purpose
#
#-------------------------------------------------------------------------
def event_has_subordinate_data(event, event_ref):
    if event and event_ref:
        return (event.get_description().strip() or
                not event.get_date_object().is_empty() or
                event.get_place_handle() or
                event.get_attribute_list() or
                event_ref.get_attribute_list() or
                event.get_note_list() or
                event.get_citation_list() or
                event.get_media_list())
    else:
        return False


#-------------------------------------------------------------------------
#
# GedcomWriter class
#
#-------------------------------------------------------------------------
class GedcomWriter(UpdateCallback):
    """
    The GEDCOM writer creates a GEDCOM file that contains the exported 
    information from the database. It derives from UpdateCallback
    so that it can provide visual feedback via a progress bar if needed.
    """

    def __init__(self, database, cmd_line=0,
                 option_box=None, callback=None):
        UpdateCallback.__init__(self, callback)

        self.dbase = database
        self.cmd_line = cmd_line
        self.dirname = None
        self.gedcom_file = None

        # The number of different stages other than any of the optional filters
        # which the write_gedcom_file method will call.
        self.progress_cnt = 5
        
        self.setup(option_box)

    def setup(self, option_box):
        """
        If the option_box is present (GUI interface), then we check the
        "private", "restrict", and "cfilter" arguments to see if we need
        to apply proxy databases.
        """
        if option_box:
            option_box.parse_options()
            self.dbase = option_box.get_filtered_database(self.dbase, self)

    def write_gedcom_file(self, filename):
        """
        Write the actual GEDCOM file to the specified filename.
        """

        self.dirname = os.path.dirname (filename)
        self.gedcom_file = open(filename, "w")
        self.__header(filename)
        self.__submitter()
        self.__individuals()
        self.__families()
        self.__sources()
        self.__repos()
        self.__notes()

        self.__writeln(0, "TRLR")
        self.gedcom_file.close()
        return True

    def __writeln(self, level, token, textlines="", limit=72):
        """
        Write a line of text to the output file in the form of:

            LEVEL TOKEN text

        If the line contains newlines, it is broken into multiple lines using
        the CONT token. If any line is greater than the limit, it will broken
        into multiple lines using CONC.
        
        """
        assert(token)
        if textlines:
            # break the line into multiple lines if a newline is found
            textlines = textlines.replace('\n\r', '\n')
            textlines = textlines.replace('\r', '\n')
            textlist = textlines.split('\n')
            token_level = level
            for text in textlist:
                # make it unicode so that breakup below does the right thin.
                text = unicode(text)
                if limit:
                    prefix = "\n%d CONC " % (level + 1)
                    txt = prefix.join(breakup(text, limit))
                else:
                    txt = text
                self.gedcom_file.write("%d %s %s\n" % (token_level, token, txt))
                token_level = level + 1
                token = "CONT"
        else:
            self.gedcom_file.write("%d %s\n" % (level, token))
    
    def __header(self, filename):
        """
        Write the GEDCOM header. 

            HEADER:=
            n HEAD {1:1}
            +1 SOUR <APPROVED_SYSTEM_ID> {1:1} 
            +2 VERS <VERSION_NUMBER> {0:1} 
            +2 NAME <NAME_OF_PRODUCT> {0:1} 
            +2 CORP <NAME_OF_BUSINESS> {0:1}           # Not used
            +3 <<ADDRESS_STRUCTURE>> {0:1}             # Not used
            +2 DATA <NAME_OF_SOURCE_DATA> {0:1}        # Not used
            +3 DATE <PUBLICATION_DATE> {0:1}           # Not used
            +3 COPR <COPYRIGHT_SOURCE_DATA> {0:1}      # Not used
            +1 DEST <RECEIVING_SYSTEM_NAME> {0:1*}     # Not used
            +1 DATE <TRANSMISSION_DATE> {0:1} 
            +2 TIME <TIME_VALUE> {0:1} 
            +1 SUBM @XREF:SUBM@ {1:1} 
            +1 SUBN @XREF:SUBN@ {0:1} 
            +1 FILE <FILE_NAME> {0:1} 
            +1 COPR <COPYRIGHT_GEDCOM_FILE> {0:1} 
            +1 GEDC {1:1}
            +2 VERS <VERSION_NUMBER> {1:1} 
            +2 FORM <GEDCOM_FORM> {1:1} 
            +1 CHAR <CHARACTER_SET> {1:1} 
            +2 VERS <VERSION_NUMBER> {0:1} 
            +1 LANG <LANGUAGE_OF_TEXT> {0:1} 
            +1 PLAC {0:1}
            +2 FORM <PLACE_HIERARCHY> {1:1} 
            +1 NOTE <GEDCOM_CONTENT_DESCRIPTION> {0:1} 
            +2 [CONT|CONC] <GEDCOM_CONTENT_DESCRIPTION> {0:M}
        
        """
        local_time = time.localtime(time.time())
        (year, mon, day, hour, minutes, sec) = local_time[0:6]
        date_str = "%d %s %d" % (day, libgedcom.MONTH[mon], year)
        time_str = "%02d:%02d:%02d" % (hour, minutes, sec)
        rname = self.dbase.get_researcher().get_name()

        self.__writeln(0, "HEAD")
        self.__writeln(1, "SOUR", "Gramps")
        self.__writeln(2, "VERS",  const.VERSION)
        self.__writeln(2, "NAME", "Gramps")
        self.__writeln(1, "DATE", date_str)
        self.__writeln(2, "TIME", time_str)
        self.__writeln(1, "SUBM", "@SUBM@")
        self.__writeln(1, "FILE", filename, limit=255)
        self.__writeln(1, "COPR", 'Copyright (c) %d %s.' % (year, rname))
        self.__writeln(1, "GEDC")
        self.__writeln(2, "VERS", "5.5")
        self.__writeln(2, "FORM", 'LINEAGE-LINKED')
        self.__writeln(1, "CHAR", "UTF-8")
        
        # write the language string if the current LANG variable 
        # matches something we know about.

        lang = os.getenv('LANG')
        if lang and len(lang) >= 2:
            lang_code = LANGUAGES.get(lang[0:2])
            if lang_code:
                self.__writeln(1, 'LANG', lang_code)

    def __submitter(self):
        """
        n @<XREF:SUBM>@ SUBM {1:1}
        +1 NAME <SUBMITTER_NAME> {1:1} 
        +1 <<ADDRESS_STRUCTURE>> {0:1}
        +1 <<MULTIMEDIA_LINK>> {0:M}              # not used
        +1 LANG <LANGUAGE_PREFERENCE> {0:3}       # not used
        +1 RFN <SUBMITTER_REGISTERED_RFN> {0:1}   # not used
        +1 RIN <AUTOMATED_RECORD_ID> {0:1}        # not used
        +1 <<CHANGE_DATE>> {0:1}                  # not used
        """
        owner = self.dbase.get_researcher()
        name = owner.get_name()
        phon = owner.get_phone()
        mail = owner.get_email()

        self.__writeln(0, "@SUBM@", "SUBM")
        self.__writeln(1, "NAME", name)
        
        # Researcher is a sub-type of LocationBase, so get_city etc. which are
        # used in __write_addr work fine. However, the database owner street is
        # stored in address, so we need to temporarily copy it into street so
        # __write_addr works properly
        owner.set_street(owner.get_address())
        self.__write_addr(1, owner)
        
        if phon:
            self.__writeln(1, "PHON", phon)
        if mail:
            self.__writeln(1, "EMAIL", mail)

    def __individuals(self):
        """
        Write the individual people to the gedcom file. 
        
        Since people like to have the list sorted by ID value, we need to go 
        through a sorting step. We need to reset the progress bar, otherwise, 
        people will be confused when the progress bar is idle.
        
        """
        self.reset(_("Writing individuals"))
        self.progress_cnt += 1
        self.update(self.progress_cnt)
        phandles = self.dbase.iter_person_handles()
        
        sorted_list = []
        for handle in phandles:
            person = self.dbase.get_person_from_handle(handle)
            if person:
                data = (person.get_gramps_id(), handle)
                sorted_list.append(data)
        sorted_list.sort()

        for data in sorted_list:
            self.__person(self.dbase.get_person_from_handle(data[1]))

    def __person(self, person):
        """
        Write out a single person.

        n @XREF:INDI@ INDI {1:1}
        +1 RESN <RESTRICTION_NOTICE> {0:1}            # not used
        +1 <<PERSONAL_NAME_STRUCTURE>> {0:M}          
        +1 SEX <SEX_VALUE> {0:1} 
        +1 <<INDIVIDUAL_EVENT_STRUCTURE>> {0:M} 
        +1 <<INDIVIDUAL_ATTRIBUTE_STRUCTURE>> {0:M} 
        +1 <<LDS_INDIVIDUAL_ORDINANCE>> {0:M} 
        +1 <<CHILD_TO_FAMILY_LINK>> {0:M} 
        +1 <<SPOUSE_TO_FAMILY_LINK>> {0:M} 
        +1 SUBM @<XREF:SUBM>@ {0:M} 
        +1 <<ASSOCIATION_STRUCTURE>> {0:M} 
        +1 ALIA @<XREF:INDI>@ {0:M} 
        +1 ANCI @<XREF:SUBM>@ {0:M} 
        +1 DESI @<XREF:SUBM>@ {0:M} 
        +1 <<SOURCE_CITATION>> {0:M} 
        +1 <<MULTIMEDIA_LINK>> {0:M} ,*
        +1 <<NOTE_STRUCTURE>> {0:M} 
        +1 RFN <PERMANENT_RECORD_FILE_NUMBER> {0:1} 
        +1 AFN <ANCESTRAL_FILE_NUMBER> {0:1} 
        +1 REFN <USER_REFERENCE_NUMBER> {0:M} 
        +2 TYPE <USER_REFERENCE_TYPE> {0:1} 
        +1 RIN <AUTOMATED_RECORD_ID> {0:1} 
        +1 <<CHANGE_DATE>> {0:1} 
        """
        if person is None:
            return
        self.__writeln(0, "@%s@" % person.get_gramps_id(),  "INDI")

        self.__names(person)
        self.__gender(person)
        self.__person_event_ref('BIRT', person.get_birth_ref())
        self.__person_event_ref('DEAT', person.get_death_ref())
        self.__remaining_events(person)
        self.__attributes(person)
        self.__lds_ords(person, 1)
        self.__child_families(person)
        self.__parent_families(person)
        self.__assoc(person, 1)
        self.__person_sources(person)
        self.__addresses(person)
        self.__photos(person.get_media_list(), 1)
        self.__url_list(person, 1)
        self.__note_references(person.get_note_list(), 1)
        self.__change(person.get_change_time(), 1)

    def __assoc(self, person, level):
        """
        n ASSO @<XREF:INDI>@ {0:M} 
        +1 RELA <RELATION_IS_DESCRIPTOR> {1:1}
        +1 <<NOTE_STRUCTURE>> {0:M} 
        +1 <<SOURCE_CITATION>> {0:M} 
        """
        for ref in person.get_person_ref_list():
            person = self.dbase.get_person_from_handle(ref.ref)
            if person:
                self.__writeln(level, "ASSO", "@%s@" % person.get_gramps_id())
                self.__writeln(level+1, "RELA", ref.get_relation())
                self.__note_references(ref.get_note_list(), level+1)
                self.__source_references(ref.get_citation_list(), level+1)

    def __note_references(self, notelist, level):
        """
        Write out the list of note handles to the current level. 
        
        We use the Gramps ID as the XREF for the GEDCOM file.

        """
        for note_handle in notelist:
            note = self.dbase.get_note_from_handle(note_handle)
            if note:
                self.__writeln(level, 'NOTE', '@%s@' % note.get_gramps_id())

    def __names(self, person):
        """
        Write the names associated with the person to the current level.
         
        Since nicknames in version < 3.3 are separate from the name structure,
        we search the attribute list to see if we can find a nickname. 
        Because we do not know the mappings, we just take the first nickname 
        we find, and add it to the primary name.
        If a nickname is present in the name structure, it has precedence

        """
        nicknames = [ attr.get_value() for attr in person.get_attribute_list()
                      if int(attr.get_type()) == gen.lib.AttributeType.NICKNAME ]
        if len(nicknames) > 0:
            nickname = nicknames[0]
        else:
            nickname = ""

        self.__person_name(person.get_primary_name(), nickname)
        for name in person.get_alternate_names():
            self.__person_name(name, "")

    def __gender(self, person):
        """
        Write out the gender of the person to the file. 
        
        If the gender is not male or female, simply do not output anything. 
        The only valid values are M (male) or F (female). So if the geneder is 
        unknown, we output nothing.
        
        """
        if person.get_gender() == gen.lib.Person.MALE:
            self.__writeln(1, "SEX", "M")
        elif person.get_gender() == gen.lib.Person.FEMALE:
            self.__writeln(1, "SEX", "F")

    def __lds_ords(self, obj, level):
        """
        Simply loop through the list of LDS ordinances, and call the function 
        that writes the LDS ordinance structure.
        """
        for lds_ord in obj.get_lds_ord_list():
            self.write_ord(lds_ord, level)

    def __remaining_events(self, person):
        """
        Output all events associated with the person that are not BIRTH or
        DEATH events. 
        
        Because all we have are event references, we have to
        extract the real event to discover the event type.
        
        """
        for event_ref in person.get_event_ref_list():
            event = self.dbase.get_event_from_handle(event_ref.ref)
            etype = int(event.get_type())

            # if the event is a birth or death, skip it.
            if etype in (gen.lib.EventType.BIRTH, gen.lib.EventType.DEATH):
                continue

            role = int(event_ref.get_role())

            # if the event role is not primary, skip the event.
            if role != gen.lib.EventRoleType.PRIMARY:
                continue
                
            val = libgedcom.PERSONALCONSTANTEVENTS.get(etype, "").strip()
                        
            if val and val.strip():
                if val in NEEDS_PARAMETER:
                    if event.get_description().strip():
                        self.__writeln(1, val, event.get_description())
                    else:
                        self.__writeln(1, val)
                else:
                    if event_has_subordinate_data(event, event_ref):
                        self.__writeln(1, val)
                    else:
                        self.__writeln(1, val, 'Y')
                    if event.get_description().strip():
                        self.__writeln(2, 'TYPE', event.get_description())
            else:
                self.__writeln(1, 'EVEN')
                if val.strip():
                    self.__writeln(2, 'TYPE', val)
                else:
                    self.__writeln(2, 'TYPE', str(event.get_type()))
                descr = event.get_description()
                if descr:
                    self.__writeln(2, 'NOTE', "Description: " + descr)
            self.__dump_event_stats(event, event_ref)

        self.__adoption_records(person)

    def __adoption_records(self, person):
        """
        Write Adoption events for each child that has been adopted.

        n ADOP
        +1 <<INDIVIDUAL_EVENT_DETAIL>>
        +1 FAMC @<XREF:FAM>@
        +2 ADOP <ADOPTED_BY_WHICH_PARENT>
        
        """
        
        adoptions = []

        for family in [ self.dbase.get_family_from_handle(fh) 
                        for fh in person.get_parent_family_handle_list() ]:
            if family is None:
                continue
            for child_ref in [ ref for ref in family.get_child_ref_list()
                               if ref.ref == person.handle ]:
                if child_ref.mrel == gen.lib.ChildRefType.ADOPTED \
                        or child_ref.frel == gen.lib.ChildRefType.ADOPTED:
                    adoptions.append((family, child_ref.frel, child_ref.mrel))

        for (fam, frel, mrel) in adoptions:
            self.__writeln(1, 'ADOP', 'Y')
            self.__writeln(2, 'FAMC', '@%s@' % fam.get_gramps_id())
            if mrel == frel:
                self.__writeln(3, 'ADOP', 'BOTH')
            elif mrel == gen.lib.ChildRefType.ADOPTED:
                self.__writeln(3, 'ADOP', 'WIFE')
            else:
                self.__writeln(3, 'ADOP', 'HUSB')

    def __attributes(self, person):
        """
        Write out the attributes to the GEDCOM file. 
        
        Since we have already looked at nicknames when we generated the names, 
        we filter them out here.

        We use the GEDCOM 5.5.1 FACT command to write out attributes not
        built in to GEDCOM.
        
        """
        
        # filter out the nicknames
        attr_list = [ attr for attr in person.get_attribute_list()
                      if attr.get_type() != gen.lib.AttributeType.NICKNAME ]

        for attr in attr_list:

            attr_type = int(attr.get_type())
            name = libgedcom.PERSONALCONSTANTATTRIBUTES.get(attr_type)
            key = str(attr.get_type())
            value = attr.get_value().strip().replace('\r', ' ')
            
            if key in ("AFN", "RFN", "REFN", "_UID", "_FSFTID"):
                self.__writeln(1, key, value)
                continue

            if key == "RESN":
                self.__writeln(1, 'RESN')
                continue

            if name and name.strip():
                self.__writeln(1, name, value)
            elif value:
                self.__writeln(1, 'FACT', value)
                self.__writeln(2, 'TYPE', key)
            else:
                continue
            self.__note_references(attr.get_note_list(), 2)
            self.__source_references(attr.get_citation_list(), 2)

    def __source_references(self, citation_list, level):
        """
        Loop through the list of citation handles, writing the information
        to the file.
        """
        for citation_handle in citation_list:
            self.__source_ref_record(level, citation_handle)

    def __addresses(self, person):
        """
        Write out the addresses associated with the person as RESI events.
        """
        for addr in person.get_address_list():
            self.__writeln(1, 'RESI')
            self.__date(2, addr.get_date_object())
            self.__write_addr(2, addr)
            if addr.get_phone():
                self.__writeln(2, 'PHON', addr.get_phone())

            self.__note_references(addr.get_note_list(), 2)
            self.__source_references(addr.get_citation_list(), 2)

    def __photos(self, media_list, level):
        """
        Loop through the list of media objects, writing the information
        to the file.
        """
        for photo in media_list:
            self.__photo(photo, level)

    def __child_families(self, person):
        """
        Write the Gramps ID as the XREF for each family in which the person
        is listed as a child.
        """
        
        # get the list of familes from the handle list
        family_list = [ self.dbase.get_family_from_handle(hndl)
                        for hndl in person.get_parent_family_handle_list() ]

        for family in family_list:
            if family:
                self.__writeln(1, 'FAMC', '@%s@' % family.get_gramps_id())

    def __parent_families(self, person):
        """
        Write the Gramps ID as the XREF for each family in which the person
        is listed as a parent.
        """

        # get the list of familes from the handle list
        family_list = [ self.dbase.get_family_from_handle(hndl)
                        for hndl in person.get_family_handle_list() ]

        for family in family_list:
            if family:
                self.__writeln(1, 'FAMS', '@%s@' % family.get_gramps_id())

    def __person_sources(self, person):
        """
        Loop through the list of citations, writing the information
        to the file.
        """
        for citation_handle in person.get_citation_list():
            self.__source_ref_record(1, citation_handle)

    def __url_list(self, obj, level):
        """
        n OBJE {1:1}
        +1 FORM <MULTIMEDIA_FORMAT> {1:1} 
        +1 TITL <DESCRIPTIVE_TITLE> {0:1} 
        +1 FILE <MULTIMEDIA_FILE_REFERENCE> {1:1}
        +1 <<NOTE_STRUCTURE>> {0:M}
        """
        for url in obj.get_url_list():
            self.__writeln(level, 'OBJE')
            self.__writeln(level+1, 'FORM', 'URL')
            if url.get_description():
                self.__writeln(level+1, 'TITL', url.get_description())
            if url.get_path():
                self.__writeln(level+1, 'FILE', url.get_path(), limit=255)

    def __families(self):
        """
        Write out the list of families, sorting by Gramps ID.
        """
        self.reset(_("Writing families"))
        self.progress_cnt += 1
        self.update(self.progress_cnt)
        # generate a list of (GRAMPS_ID, HANDLE) pairs. This list
        # can then be sorted by the sort routine, which will use the
        # first value of the tuple as the sort key. 
        sorted_list = sort_handles_by_id(self.dbase.get_family_handles(),
                                         self.dbase.get_family_from_handle)

        # loop through the sorted list, pulling of the handle. This list
        # has already been sorted by GRAMPS_ID
        for family_handle in [hndl[1] for hndl in sorted_list]:
            self.__family(self.dbase.get_family_from_handle(family_handle))

    def __family(self, family):
        """
        n @<XREF:FAM>@ FAM {1:1}
        +1 RESN <RESTRICTION_NOTICE> {0:1)
        +1 <<FAMILY_EVENT_STRUCTURE>> {0:M} 
        +1 HUSB @<XREF:INDI>@ {0:1}
        +1 WIFE @<XREF:INDI>@ {0:1}
        +1 CHIL @<XREF:INDI>@ {0:M}
        +1 NCHI <COUNT_OF_CHILDREN> {0:1}
        +1 SUBM @<XREF:SUBM>@ {0:M}
        +1 <<LDS_SPOUSE_SEALING>> {0:M}
        +1 REFN <USER_REFERENCE_NUMBER> {0:M}
        """
        if family is None:
            return
        gramps_id = family.get_gramps_id()

        self.__writeln(0, '@%s@' % gramps_id, 'FAM' )

        self.__family_reference('HUSB', family.get_father_handle())
        self.__family_reference('WIFE', family.get_mother_handle())

        self.__lds_ords(family, 1)
        self.__family_events(family)
        self.__family_attributes(family.get_attribute_list(), 1)
        self.__family_child_list(family.get_child_ref_list())
        self.__source_references(family.get_citation_list(), 1)
        self.__photos(family.get_media_list(), 1)
        self.__note_references(family.get_note_list(), 1)
        self.__change(family.get_change_time(), 1)

    def __family_child_list(self, child_ref_list):
        """
        Write the child XREF values to the GEDCOM file. 
        """
        child_list = [ 
            self.dbase.get_person_from_handle(cref.ref).get_gramps_id()
            for cref in child_ref_list]

        for gid in child_list:
            if gid is None: continue
            self.__writeln(1, 'CHIL', '@%s@' % gid)

    def __family_reference(self, token, person_handle):
        """
        Write the family reference to the file. 
        
        This is either 'WIFE' or 'HUSB'. As usual, we use the Gramps ID as the 
        XREF value.
        
        """
        if person_handle:
            person = self.dbase.get_person_from_handle(person_handle)
            if person:
                self.__writeln(1, token, '@%s@' % person.get_gramps_id())

    def __family_events(self, family):
        """
        Output the events associated with the family. 
        
        Because all we have are event references, we have to extract the real 
        event to discover the event type.
        
        """
        for event_ref in family.get_event_ref_list():
            event = self.dbase.get_event_from_handle(event_ref.ref)
            if event is None: continue
            etype = int(event.get_type())
            val = libgedcom.FAMILYCONSTANTEVENTS.get(etype)
            
            if val:
                if event_has_subordinate_data(event, event_ref):
                    self.__writeln(1, val)
                else:
                    self.__writeln(1, val, 'Y')

                if event.get_type() == gen.lib.EventType.MARRIAGE:
                    self.__family_event_attrs(event.get_attribute_list(), 2) 

                if event.get_description().strip() != "":
                    self.__writeln(2, 'TYPE', event.get_description())
            else:
                self.__writeln(1, 'EVEN')
                the_type = str(event.get_type())
                if the_type:
                    self.__writeln(2, 'TYPE', the_type)
                descr = event.get_description()
                if descr:
                    self.__writeln(2, 'NOTE', "Description: " + descr)

            self.__dump_event_stats(event, event_ref)

    def __family_event_attrs(self, attr_list, level):
        """
        Write the attributes associated with the family event. 
        
        The only ones we really care about are FATHER_AGE and MOTHER_AGE which 
        we translate to WIFE/HUSB AGE attributes.
        
        """
        for attr in attr_list:
            if attr.get_type() == gen.lib.AttributeType.FATHER_AGE:
                self.__writeln(level, 'HUSB')
                self.__writeln(level+1, 'AGE', attr.get_value())
            elif attr.get_type() == gen.lib.AttributeType.MOTHER_AGE:
                self.__writeln(level, 'WIFE')
                self.__writeln(level+1, 'AGE', attr.get_value())

    def __family_attributes(self, attr_list, level):
        """
        Write out the attributes associated with a family to the GEDCOM file.
         
        Since we have already looked at nicknames when we generated the names, 
        we filter them out here.

        We use the GEDCOM 5.5.1 FACT command to write out attributes not
        built in to GEDCOM.
        
        """

        for attr in attr_list:
            
            attr_type = int(attr.get_type())
            name = libgedcom.FAMILYCONSTANTATTRIBUTES.get(attr_type)
            key = str(attr.get_type())
            value = attr.get_value().replace('\r', ' ')

            if key in ("AFN", "RFN", "REFN", "_UID"):
                self.__writeln(1, key, value)
                continue
            
            if name and name.strip():
                self.__writeln(1, name, value)
                continue
            else:
                self.__writeln(1, 'FACT', value)
                self.__writeln(2, 'TYPE', key)

            self.__note_references(attr.get_note_list(), level+1)
            self.__source_references(attr.get_citation_list(), 
                                     level+1)

    def __sources(self):
        """
        Write out the list of sources, sorting by Gramps ID.
        """
        self.reset(_("Writing sources"))
        self.progress_cnt += 1
        self.update(self.progress_cnt)
        sorted_list = sort_handles_by_id(self.dbase.get_source_handles(),
                                         self.dbase.get_source_from_handle)

        for (source_id, handle) in sorted_list:
            source = self.dbase.get_source_from_handle(handle)
            if source is None: continue
            self.__writeln(0, '@%s@' % source_id, 'SOUR')
            if source.get_title():
                self.__writeln(1, 'TITL', source.get_title())

            if source.get_author():
                self.__writeln(1, "AUTH", source.get_author())

            if source.get_publication_info():
                self.__writeln(1, "PUBL", source.get_publication_info())

            if source.get_abbreviation():
                self.__writeln(1, 'ABBR', source.get_abbreviation())

            self.__photos(source.get_media_list(), 1)

            for reporef in source.get_reporef_list():
                self.__reporef(reporef, 1)
                break

            self.__note_references(source.get_note_list(), 1)
            self.__change(source.get_change_time(), 1)

    def __notes(self):
        """
        Write out the list of notes, sorting by Gramps ID.
        """
        self.reset(_("Writing notes"))
        self.progress_cnt += 1
        self.update(self.progress_cnt)
        sorted_list = sort_handles_by_id(self.dbase.get_note_handles(),
                                         self.dbase.get_note_from_handle)

        for note_handle in [hndl[1] for hndl in sorted_list]:
            note = self.dbase.get_note_from_handle(note_handle)
            if note is None: continue
            self.__note_record(note)
            
    def __note_record(self, note):
        """
        n @<XREF:NOTE>@ NOTE <SUBMITTER_TEXT> {1:1} 
        +1 [ CONC | CONT] <SUBMITTER_TEXT> {0:M}
        +1 <<SOURCE_CITATION>> {0:M} 
        +1 REFN <USER_REFERENCE_NUMBER> {0:M} 
        +2 TYPE <USER_REFERENCE_TYPE> {0:1} 
        +1 RIN <AUTOMATED_RECORD_ID> {0:1} 
        +1 <<CHANGE_DATE>> {0:1} 
        """
        if note:
            self.__writeln(0, '@%s@' % note.get_gramps_id(),  'NOTE ' + note.get())

    def __repos(self):
        """
        Write out the list of repositories, sorting by Gramps ID.

        REPOSITORY_RECORD:=
        n @<XREF:REPO>@ REPO {1:1}
        +1 NAME <NAME_OF_REPOSITORY> {1:1}
        +1 <<ADDRESS_STRUCTURE>> {0:1}
        +1 <<NOTE_STRUCTURE>> {0:M}
        +1 REFN <USER_REFERENCE_NUMBER> {0:M}
        +2 TYPE <USER_REFERENCE_TYPE> {0:1}
        +1 RIN <AUTOMATED_RECORD_ID> {0:1}
        +1 <<CHANGE_DATE>> {0:1}
        """
        self.reset(_("Writing repositories"))
        self.progress_cnt += 1
        self.update(self.progress_cnt)
        sorted_list = sort_handles_by_id(self.dbase.get_repository_handles(),
                                         self.dbase.get_repository_from_handle)

        # GEDCOM only allows for a single repository per source

        for (repo_id, handle) in sorted_list:
            repo = self.dbase.get_repository_from_handle(handle)
            if repo is None: continue
            self.__writeln(0, '@%s@' % repo_id, 'REPO' )
            if repo.get_name():
                self.__writeln(1, 'NAME', repo.get_name())
            for addr in repo.get_address_list():
                self.__write_addr(1, addr)
                if addr.get_phone():
                    self.__writeln(1, 'PHON', addr.get_phone())
            for url in repo.get_url_list():
                if int(url.get_type()) == gen.lib.UrlType.EMAIL:
                    self.__writeln(1, 'EMAIL', url.get_path())
                elif int(url.get_type()) == gen.lib.UrlType.WEB_HOME:
                    self.__writeln(1, 'WWW', url.get_path())
            self.__note_references(repo.get_note_list(), 1)

    def __reporef(self, reporef, level):
        """
        n REPO [ @XREF:REPO@ | <NULL>] {1:1}
        +1 <<NOTE_STRUCTURE>> {0:M}
        +1 CALN <SOURCE_CALL_NUMBER> {0:M}
        +2 MEDI <SOURCE_MEDIA_TYPE> {0:1}
        """

        if reporef.ref is None:
            return

        repo = self.dbase.get_repository_from_handle(reporef.ref)
        if repo is None:
            return
        
        repo_id = repo.get_gramps_id()

        self.__writeln(level, 'REPO', '@%s@' % repo_id )

        self.__note_references(reporef.get_note_list(), level+1)

        if reporef.get_call_number():
            self.__writeln(level+1, 'CALN', reporef.get_call_number() )
            if reporef.get_media_type():
                self.__writeln(level+2, 'MEDI', str(reporef.get_media_type()))

    def __person_event_ref(self, key, event_ref):
        """
        Write out the BIRTH and DEATH events for the person.
        """
        if event_ref:
            event = self.dbase.get_event_from_handle(event_ref.ref)
            if event_has_subordinate_data(event, event_ref):
                self.__writeln(1, key)
            else:
                self.__writeln(1, key, 'Y')
            if event.get_description().strip() != "":
                self.__writeln(2, 'TYPE', event.get_description())
            self.__dump_event_stats(event, event_ref)

    def __change(self, timeval, level):
        """
        CHANGE_DATE:=
            n CHAN {1:1}
            +1 DATE <CHANGE_DATE> {1:1}
            +2 TIME <TIME_VALUE> {0:1}
            +1 <<NOTE_STRUCTURE>>          # not used
        """
        self.__writeln(level, 'CHAN')
        time_val = time.localtime(timeval)
        self.__writeln(level+1, 'DATE', '%d %s %d' % (
                time_val[2], libgedcom.MONTH[time_val[1]], time_val[0]))
        self.__writeln(level+2, 'TIME', '%02d:%02d:%02d' % (
                time_val[3], time_val[4], time_val[5]))

    def __dump_event_stats(self, event, event_ref):
        """
        Write the event details for the event, using the event and event 
        reference information. 
        
        GEDCOM does not make a distinction between the two.
        
        """
        dateobj = event.get_date_object()
        self.__date(2, dateobj)
        if self.__datewritten:
            # write out TIME if present
            times = [ attr.get_value() for attr in event.get_attribute_list()
                      if int(attr.get_type()) == gen.lib.AttributeType.TIME ]
            # Not legal, but inserted by PhpGedView
            if len(times) > 0:
                time = times[0]
                self.__writeln(3, 'TIME', time)

        place = None

        if event.get_place_handle():
            place = self.dbase.get_place_from_handle(event.get_place_handle())
            self.__place(place, 2)

        for attr in event.get_attribute_list():
            attr_type = attr.get_type()
            if attr_type == gen.lib.AttributeType.CAUSE:
                self.__writeln(2, 'CAUS', attr.get_value())
            elif attr_type == gen.lib.AttributeType.AGENCY:
                self.__writeln(2, 'AGNC', attr.get_value())

        for attr in event_ref.get_attribute_list():
            attr_type = attr.get_type()
            if attr_type == gen.lib.AttributeType.AGE:
                self.__writeln(2, 'AGE', attr.get_value())
            elif attr_type == gen.lib.AttributeType.FATHER_AGE:
                self.__writeln(2, 'HUSB')
                self.__writeln(3, 'AGE', attr.get_value())
            elif attr_type == gen.lib.AttributeType.MOTHER_AGE:
                self.__writeln(2, 'WIFE')
                self.__writeln(3, 'AGE', attr.get_value())

        self.__note_references(event.get_note_list(), 2)
        self.__source_references(event.get_citation_list(), 2)

        self.__photos(event.get_media_list(), 2)
        if place:
            self.__photos(place.get_media_list(), 2)

    def write_ord(self, lds_ord, index):
        """
          LDS_INDIVIDUAL_ORDINANCE:=
          [
             n [ BAPL | CONL ] {1:1}
            +1 DATE <DATE_LDS_ORD> {0:1}
            +1 TEMP <TEMPLE_CODE> {0:1}
            +1 PLAC <PLACE_LIVING_ORDINANCE> {0:1}
            +1 STAT <LDS_BAPTISM_DATE_STATUS> {0:1}
              +2 DATE <CHANGE_DATE> {1:1}
            +1 <<NOTE_STRUCTURE>> {0:M}
            +1 <<SOURCE_CITATION>> {0:M} p.39
          |
             n ENDL {1:1}
            +1 DATE <DATE_LDS_ORD> {0:1}
            +1 TEMP <TEMPLE_CODE> {0:1}
            +1 PLAC <PLACE_LIVING_ORDINANCE> {0:1}
            +1 STAT <LDS_ENDOWMENT_DATE_STATUS> {0:1}
              +2 DATE <CHANGE_DATE> {1:1}
            +1 <<NOTE_STRUCTURE>> {0:M}
            +1 <<SOURCE_CITATION>> {0:M}
          |
             n SLGC {1:1}
            +1 DATE <DATE_LDS_ORD> {0:1}
            +1 TEMP <TEMPLE_CODE> {0:1}
            +1 PLAC <PLACE_LIVING_ORDINANCE> {0:1}
            +1 FAMC @<XREF:FAM>@ {1:1}
            +1 STAT <LDS_CHILD_SEALING_DATE_STATUS> {0:1}
              +2 DATE <CHANGE_DATE> {1:1}
            +1 <<NOTE_STRUCTURE>> {0:M}
            +1 <<SOURCE_CITATION>> {0:M}
          ]
        """

        self.__writeln(index, LDS_ORD_NAME[lds_ord.get_type()])
        self.__date(index + 1, lds_ord.get_date_object())
        if lds_ord.get_family_handle():
            family_handle = lds_ord.get_family_handle()
            family = self.dbase.get_family_from_handle(family_handle)
            if family:
                self.__writeln(index+1, 'FAMC', '@%s@' % family.get_gramps_id())
        if lds_ord.get_temple():
            self.__writeln(index+1, 'TEMP', lds_ord.get_temple())
        if lds_ord.get_place_handle():
            self.__place(
                self.dbase.get_place_from_handle(lds_ord.get_place_handle()), 2)
        if lds_ord.get_status() != gen.lib.LdsOrd.STATUS_NONE:
            self.__writeln(2, 'STAT', LDS_STATUS[lds_ord.get_status()])
        
        self.__note_references(lds_ord.get_note_list(), index+1)
        self.__source_references(lds_ord.get_citation_list(), index+1)

    def __date(self, level, date):
        """
        Write the 'DATE' GEDCOM token, along with the date in GEDCOM's
        expected format.
        """
        self.__datewritten = True
        start = date.get_start_date()
        if start != gen.lib.Date.EMPTY:
            cal = date.get_calendar()
            mod = date.get_modifier()
            quality = date.get_quality()
            if quality in libgedcom.DATE_QUALITY:
                qual_text = libgedcom.DATE_QUALITY[quality] + " "
            else:
                qual_text = ""
            if mod == gen.lib.Date.MOD_SPAN:
                val = "%sFROM %s TO %s" % (
                    qual_text,
                    libgedcom.make_gedcom_date(start, cal, mod, None), 
                    libgedcom.make_gedcom_date(date.get_stop_date(), 
                                               cal, mod, None))
            elif mod == gen.lib.Date.MOD_RANGE:
                val = "%sBET %s AND %s" % (
                    qual_text,
                    libgedcom.make_gedcom_date(start, cal, mod, None), 
                    libgedcom.make_gedcom_date(date.get_stop_date(), 
                                               cal, mod, None))
            else:
                val = libgedcom.make_gedcom_date(start, cal, mod, quality)
            self.__writeln(level, 'DATE', val)
        elif date.get_text():
            self.__writeln(level, 'DATE', date.get_text())
        else:
            self.__datewritten = False

    def __person_name(self, name, attr_nick):
        """
        n NAME <NAME_PERSONAL> {1:1} 
        +1 NPFX <NAME_PIECE_PREFIX> {0:1} 
        +1 GIVN <NAME_PIECE_GIVEN> {0:1} 
        +1 NICK <NAME_PIECE_NICKNAME> {0:1} 
        +1 SPFX <NAME_PIECE_SURNAME_PREFIX {0:1} 
        +1 SURN <NAME_PIECE_SURNAME> {0:1} 
        +1 NSFX <NAME_PIECE_SUFFIX> {0:1} 
        +1 <<SOURCE_CITATION>> {0:M} 
        +1 <<NOTE_STRUCTURE>> {0:M} 
        """
        gedcom_name = name.get_gedcom_name()

        firstname = name.get_first_name().strip()
        surns = []
        surprefs = []
        for surn in name.get_surname_list():
            surns.append(surn.get_surname().replace('/', '?'))
            if surn.get_connector():
                #we store connector with the surname
                surns[-1] = surns[-1] + ' ' + surn.get_connector()
            surprefs.append(surn.get_prefix().replace('/', '?'))
        surname = ', '.join(surns)
        surprefix = ', '.join(surprefs)
        suffix = name.get_suffix()
        title = name.get_title()
        nick = name.get_nick_name()
        if nick.strip() == '':
            nick = attr_nick

        self.__writeln(1, 'NAME', gedcom_name)
        if int(name.get_type()) == gen.lib.NameType.BIRTH:
            pass
        elif int(name.get_type()) == gen.lib.NameType.MARRIED:
            self.__writeln(2, 'TYPE', 'married')
        elif int(name.get_type()) == gen.lib.NameType.AKA:
            self.__writeln(2, 'TYPE', 'aka')
        else:
            self.__writeln(2, 'TYPE', name.get_type().xml_str())

        if firstname:
            self.__writeln(2, 'GIVN', firstname)
        if surprefix:
            self.__writeln(2, 'SPFX', surprefix)
        if surname:
            self.__writeln(2, 'SURN', surname)
        if name.get_suffix():
            self.__writeln(2, 'NSFX', suffix)
        if name.get_title():
            self.__writeln(2, 'NPFX', title)
        if nick:
            self.__writeln(2, 'NICK', nick)

        self.__source_references(name.get_citation_list(), 2)
        self.__note_references(name.get_note_list(), 2)

    def __source_ref_record(self, level, citation_handle):
        """
        n SOUR @<XREF:SOUR>@ /* pointer to source record */ {1:1} 
        +1 PAGE <WHERE_WITHIN_SOURCE> {0:1} 
        +1 EVEN <EVENT_TYPE_CITED_FROM> {0:1} 
        +2 ROLE <ROLE_IN_EVENT> {0:1} 
        +1 DATA {0:1}
        +2 DATE <ENTRY_RECORDING_DATE> {0:1} 
        +2 TEXT <TEXT_FROM_SOURCE> {0:M} 
        +3 [ CONC | CONT ] <TEXT_FROM_SOURCE> {0:M}
        +1 QUAY <CERTAINTY_ASSESSMENT> {0:1} 
        +1 <<MULTIMEDIA_LINK>> {0:M} ,*
        +1 <<NOTE_STRUCTURE>> {0:M} 
        """

        citation = self.dbase.get_citation_from_handle(citation_handle)
                
        src_handle = citation.get_reference_handle()
        if src_handle is None:
            return

        src = self.dbase.get_source_from_handle(src_handle)
        if src is None:
            return

        # Reference to the source
        self.__writeln(level, "SOUR", "@%s@" % src.get_gramps_id())
        if citation.get_page() != "":
        # PAGE <WHERE_WITHIN_SOURCE> can not have CONC lines.
        # WHERE_WITHIN_SOURCE:= {Size=1:248}
        # Maximize line to 248 and set limit to 248, for no line split
            self.__writeln(level+1, 'PAGE', citation.get_page()[0:248], 
                           limit=248)


        conf = min(citation.get_confidence_level(), 
                   gen.lib.Citation.CONF_VERY_HIGH)
        if conf != gen.lib.Citation.CONF_NORMAL and conf != -1:
            self.__writeln(level+1, "QUAY", QUALITY_MAP[conf])

        if not citation.get_date_object().is_empty():
            self.__writeln(level+1, 'DATA')
            self.__date(level+2, citation.get_date_object())

        if len(citation.get_note_list()) > 0:

            note_list = [ self.dbase.get_note_from_handle(h) 
                          for h in citation.get_note_list() ]
            note_list = [ n for n in note_list 
                          if n.get_type() == gen.lib.NoteType.SOURCE_TEXT]

            if note_list:
                ref_text = note_list[0].get()
            else:
                ref_text = ""

            if ref_text != "" and citation.get_date_object().is_empty():
                self.__writeln(level+1, 'DATA')
            if ref_text != "":
                self.__writeln(level+2, "TEXT", ref_text)

            note_list = [ self.dbase.get_note_from_handle(h) 
                          for h in citation.get_note_list() ]
            note_list = [ n.handle for n in note_list 
                          if n and n.get_type() != gen.lib.NoteType.SOURCE_TEXT]
            self.__note_references(note_list, level+1)

        self.__photos(citation.get_media_list(), level+1)
            
        if "EVEN" in citation.get_data_map().keys():
            self.__writeln(level+1, "EVEN", citation.get_data_map()["EVEN"])
            if "EVEN:ROLE" in citation.get_data_map().keys():
                self.__writeln(level+2, "ROLE", 
                               citation.get_data_map()["EVEN:ROLE"])
                

    def __photo(self, photo, level):
        """
        n OBJE {1:1}
        +1 FORM <MULTIMEDIA_FORMAT> {1:1} 
        +1 TITL <DESCRIPTIVE_TITLE> {0:1} 
        +1 FILE <MULTIMEDIA_FILE_REFERENCE> {1:1}
        +1 <<NOTE_STRUCTURE>> {0:M}
        """
        photo_obj_id = photo.get_reference_handle()
        photo_obj = self.dbase.get_object_from_handle(photo_obj_id)
        if photo_obj:
            mime = photo_obj.get_mime_type()
            form = MIME2GED.get(mime, mime)
            path = media_path_full(self.dbase, photo_obj.get_path())
            if not os.path.isfile(path):
                return
            self.__writeln(level, 'OBJE')
            if form:
                self.__writeln(level+1, 'FORM', form)
            self.__writeln(level+1, 'TITL', photo_obj.get_description())
            self.__writeln(level+1, 'FILE', path, limit=255)

            self.__note_references(photo_obj.get_note_list(), level+1)

    def __place(self, place, level):
        """
        PLACE_STRUCTURE:=
            n PLAC <PLACE_NAME> {1:1}
            +1 FORM <PLACE_HIERARCHY> {0:1}
            +1 FONE <PLACE_PHONETIC_VARIATION> {0:M}  # not used
            +2 TYPE <PHONETIC_TYPE> {1:1}
            +1 ROMN <PLACE_ROMANIZED_VARIATION> {0:M} # not used
            +2 TYPE <ROMANIZED_TYPE> {1:1}
            +1 MAP {0:1}
            +2 LATI <PLACE_LATITUDE> {1:1}
            +2 LONG <PLACE_LONGITUDE> {1:1}
            +1 <<NOTE_STRUCTURE>> {0:M} 
        """
        if place is None: return
        place_name = place.get_title()
        self.__writeln(level, "PLAC", place_name.replace('\r', ' '), limit=120)
        longitude = place.get_longitude()
        latitude = place.get_latitude()
        if longitude and latitude:
            (latitude, longitude) = conv_lat_lon(latitude, longitude, "GEDCOM")
        if longitude and latitude:
            self.__writeln(level+1, "MAP")
            self.__writeln(level+2, 'LATI', latitude)
            self.__writeln(level+2, 'LONG', longitude)

        # The Gedcom standard shows that an optional address structure can
        # be written out in the event detail.
        # http://homepages.rootsweb.com/~pmcbride/gedcom/55gcch2.htm#EVENT_DETAIL
        location = place.get_main_location()
        if location and not location.is_empty():
            self.__write_addr(level, location)
            if location.get_phone():
                self.__writeln(level, 'PHON', location.get_phone())

        self.__note_references(place.get_note_list(), level+1)

    def __write_addr(self, level, addr):
        """
        n ADDR <ADDRESS_LINE> {0:1} 
        +1 CONT <ADDRESS_LINE> {0:M}
        +1 ADR1 <ADDRESS_LINE1> {0:1}  (Street)
        +1 ADR2 <ADDRESS_LINE2> {0:1}  (Locality)
        +1 CITY <ADDRESS_CITY> {0:1}
        +1 STAE <ADDRESS_STATE> {0:1}
        +1 POST <ADDRESS_POSTAL_CODE> {0:1}
        +1 CTRY <ADDRESS_COUNTRY> {0:1}

        This is done along the lines suggested by Tamura Jones in
        http://www.tamurajones.net/GEDCOMADDR.xhtml as a result of bug 6382.
        "GEDCOM writers should always use the structured address format,
        and it use it for all addresses, including the submitter address and
        their own corporate address." "Vendors that want their product to pass
        even the strictest GEDCOM validation, should include export to the old
        free-form format..." [This goes on to say the free-form should be an
        option, but we have not made it an option in Gramps].

        @param level: The level number for the ADDR tag
        @type level: Integer
        @param addr: The location or address
        @type addr: [a super-type of] LocationBase
        """
        if addr.get_street() or addr.get_locality() or addr.get_city() or \
           addr.get_state() or addr.get_postal_code or addr.get_country():
            self.__writeln(level, 'ADDR', addr.get_street())
            if addr.get_locality():
                self.__writeln(level + 1, 'CONT', addr.get_locality())
            if addr.get_city():
                self.__writeln(level + 1, 'CONT', addr.get_city())
            if addr.get_state():
                self.__writeln(level + 1, 'CONT', addr.get_state())
            if addr.get_postal_code():
                self.__writeln(level + 1, 'CONT', addr.get_postal_code())
            if addr.get_country():
                self.__writeln(level + 1, 'CONT', addr.get_country())
            
            if addr.get_street():
                self.__writeln(level + 1, 'ADR1', addr.get_street())
            if addr.get_locality():
                self.__writeln(level + 1, 'ADR2', addr.get_locality())
            if addr.get_city():
                self.__writeln(level + 1, 'CITY', addr.get_city())
            if addr.get_state():
                self.__writeln(level + 1, 'STAE', addr.get_state())
            if addr.get_postal_code():
                self.__writeln(level + 1, 'POST', addr.get_postal_code())
            if addr.get_country():
                self.__writeln(level + 1, 'CTRY', addr.get_country())

#-------------------------------------------------------------------------
#
#
#
#-------------------------------------------------------------------------
def export_data(database, filename, msg_callback, option_box=None, callback=None):
    """
    External interface used to register with the plugin system.
    """
    ret = False
    try:
        ged_write = GedcomWriter(database, 0, option_box, callback)
        ret = ged_write.write_gedcom_file(filename)
    except IOError, msg:
        msg2 = _("Could not create %s") % filename
        msg_callback(msg2, str(msg))
    except Errors.DatabaseError, msg:
        msg_callback(_("Export failed"), str(msg))
    return ret