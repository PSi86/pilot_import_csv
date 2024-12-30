'''
Created by Peter Simandl "psi" in 12.2024
    
Importer for Pilot and Team Registrations from Registration Forms (eg: WordPress Contact Form 7)
Currently Only CSV Format is supported, but JSON could be implemented with minor changes if needed

Usage: TODO
Works with Rotorhazard 4.0
'''

import logging
import csv
import RHUtils
import Database
from eventmanager import Evt
from data_import import DataImporter
from Database import ProgramMethod
from RHUI import UIField, UIFieldType, UIFieldSelectOption

logger = logging.getLogger(__name__)

def import_wp_contactform_csv(importer_class, rhapi, source, args):

    teamsize_max = 1 # for checking of pilot 1, pilot 2, pilot N named keys in the registration
    report_optional_errors=False

    reg_type_key="registertype" #"type_select"
    single_reg_str="as a singlepilot" #"Einzelpilot"
    team_reg_str="as a teampilot" #"Teamanmeldung"

    default_team="Z"
    default_country="Germany"

    # ext_to_int_map_mandatory = {
    # "teamname": "attributes:team_callsign",
    # "registertype": "attributes:solo_mode", #"type_select": "attributes:solo_mode",
    # }
    ext_to_int_map_mandatory = {}

    ext_to_int_map_team_optional = {
    "team_logo": "logo",
    }

    ext_to_int_map_pilot_mandatory = {
    "Pilot Name ": "name",
    "Pilot Nickname ": "callsign",
    }

    ext_to_int_map_pilot_optional = {
    "Pilot Phone ": "phone",
    "Pilot Mail ": "mail",
    }
    
    validated_pilots=[]
    import_errors=[]

    # abort if no data is provided
    if not source:
        return False
    
    #source is a binary string (b')
    source_str=source.decode('utf-8')
    source_str=source_str.strip()

    try:
        data_csv = csv.DictReader(source_str.splitlines())
    except Exception as ex:
        logger.error("Unable to import file: {}".format(str(ex)))
        return False

    if 'max_teamsize' in args and int(args['max_teamsize'])>0:
        teamsize_max=int(args['max_teamsize'])
    if 'report_optional_errors' in args and args['report_optional_errors']:
        report_optional_errors=True

    # load valid registration data into import data structure validated_pilots[]
    # iterate registered teams / pilots - one registration can be one or more pilots
    for registration in data_csv:
        #print(registration)
        #iterate mandatory fields (keys)
        errors_mandatory=[]
        errors_optional=[]
        temp_dict={}
        
        pilot_counter=0
        data_valid=False
        teamsize=teamsize_max #reset for every registration line

        # if there is a special key in registration data to detect team size we can read it here and override it 
        if reg_type_key in registration:
            if registration[reg_type_key]==single_reg_str:
                teamsize=1
                registration[reg_type_key]='1' # solo_mode = 1
            else:
                registration[reg_type_key]='0' # solo_mode = 0 (Team-Mode)
        else:
            teamsize=teamsize_max
        
        #validate_fields is true when all mandatory fields are found. If mandatory parameter is false then function always returns True
        if(validate_fields(registration, ext_to_int_map_mandatory, temp_dict, errors_mandatory, True)):
            #current_team=temp_dict['team']
            validate_fields(registration, ext_to_int_map_team_optional, temp_dict, errors_optional, False)
            # at this point we have all importable team related data in temp_dict, now we import pilot related data
            # to make sure we do not copy data from one pilot to the next we just use this copy of the temp_dict 
            backup_dict=temp_dict

            while pilot_counter<teamsize:
                pilot_counter+=1
                temp_dict=backup_dict.copy()
                if(validate_fields(registration, ext_to_int_map_pilot_mandatory, temp_dict, errors_mandatory, True, pilot_counter)):
                    validate_fields(registration, ext_to_int_map_pilot_optional, temp_dict, errors_optional, False, pilot_counter)
                    validated_pilots.append(temp_dict)

        #print(error_list)

        if(report_optional_errors and len(errors_optional)>0): errors_mandatory.extend(errors_optional)
        if(len(errors_mandatory)>0): import_errors.extend([registration,errors_mandatory])
    
    # TODO change print to different reporting: logger, ui message, etc
    #logger.debug("GC: Creating UI Device Select Options")
    logger.info("Valid Pilots in Registration Data: {}".format(len(validated_pilots)))
    rhapi.ui.message_notify("Valid Pilots in Registration Data: {}".format(len(validated_pilots)))
    logger.info("Errors during Import: {}".format(import_errors))
    rhapi.ui.message_notify("Errors during Import: {}".format(import_errors))
    #print(len(validated_pilots))
    logger.info("Valid Registration Data: {}".format(validated_pilots))
    #print(len(import_errors))
    #print(import_errors)

    #sanity_good=False
    sanity_good=True
    # TODO more sanity checks: 
    # - search for duplicate callsigns (they are used to find pilots in DB)
    # - remove whitespaces at the beginning and end of each field
    # - normalize phone numbers to 0049...

    #TODO: search for double pilot callsigns
    #for pilot in validated_pilots:

     # abort if sanity check is unsucessful
    if not sanity_good:
        return False
    
    # if sanity checks where sucessfull reset if option was selected, then start import process
    if 'reset_pilots' in args and args['reset_pilots']:
        rhapi.db.pilots_reset()
    
    db_pilots = rhapi.db.pilots

    #iterate through pilot array from json
    for input_pilot in validated_pilots:

        #source_id = input_pilot['id']

        db_match = None
        # iterate database of pilots 
        for db_pilot in db_pilots:
            #if the pilot DB has not cleared we need to be careful about team assignment
            # idea: always clear pilot db -> problem: not possible to add pilots by importing a second registration file
            # 

            #search for pilot in db with same callsign as import pilot
            if db_pilot.callsign == input_pilot['callsign']:
                db_match = db_pilot
                break
        
        # delete data elements (keys) from current pilot json data which are not available in our database
        for item in list(input_pilot.keys()):
            if item not in ['name', 
                'callsign',
                'phonetic',
                'team',
                'color', 
                'attributes'
                ]:
                del input_pilot[item]

        if db_match:
            db_pilot, _ = rhapi.db.pilot_alter(db_match.id, **input_pilot)
        else:
            #new pilot will be added - set default team
            # TODO scan pilot db for identical team_callsign and put new pilot in same team.
            # this cannot be done on the registation data as it does not know the Rotorhazard internal team assignment.
            # so we need to to it in the rotorhazard DB
            input_pilot['team']=default_team # TODO UNTESTED!
            
            # if attributes are not deleted there will be an error at pilot_add: TypeError: DatabaseAPI.pilot_add() got an unexpected keyword argument 'attributes' TODO!!!
            if 'attributes' in input_pilot:
                input_pilot_attributes=input_pilot['attributes'].copy()
                del input_pilot['attributes']
                db_pilot = rhapi.db.pilot_add(**input_pilot)
                #db_pilot, _ = rhapi.db.pilot_alter(db_pilot.id, **input_pilot)
                db_pilot = rhapi.db.pilot_alter(db_pilot.id, attributes=input_pilot_attributes)
            else:
                db_pilot = rhapi.db.pilot_add(**input_pilot)

        # TODO: why this???
        #input_pilot['source_id'] = source_id
        #input_pilot['db_id'] = db_pilot.id

    return True

def register_handlers(args):
    for importer in [
        DataImporter(
            'Pilot Registrations CSV',
            import_wp_contactform_csv,
            None,
            [
                UIField('reset_pilots', "Reset Pilots", UIFieldType.CHECKBOX, value=False),
                UIField('max_teamsize', "Max Pilots per Registration", UIFieldType.BASIC_INT, value=2),
                UIField('report_optional_errors', "Report Missing / Empty optional Fields", UIFieldType.CHECKBOX, value=False),
            ]
        ),
    ]:
        args['register_fn'](importer)

def initialize(rhapi):
    #rhapi.fields.register_pilot_attribute(UIField('team_callsign', "Team Name", UIFieldType.TEXT)) #now done in teamrace_manager plugin
    #rhapi.fields.register_pilot_attribute(UIField('solo_mode', "Solo Mode", UIFieldType.CHECKBOX)) #now done in teamrace_manager plugin
   
    rhapi.events.on(Evt.DATA_IMPORT_INITIALIZE, register_handlers)


# registration: row from registration data
# fieldmap: {key=registrationField, value=rotorhazardField}
# workdict: found+valid fields will be put in workdict with rotorhazardKey from fieldmap
# errorlist: errors are written to this dictionary
# allFieldsMandatory: if set True the workdict will only be updated if all fields from fieldmap are found in registration
# field_N: if not 0 the passed number will be appended to the fieldnames in fieldmap

def validate_fields(registration, fieldmap:dict, workdict:dict, errorlist:list, allFieldsMandatory:bool=True, field_N:int=0):

    found_all=True
    temp_dict={}
    errors=[]

    for key in list(fieldmap.keys()):
        
        #modify keyname depeding on field_N param
        if field_N>0:
            key_N=key+str(field_N)
        else:
            key_N=key

        if key_N in list(registration.keys()):
            if(len(registration[key_N])>0): #check if field not empty
                if('attributes' in fieldmap[key]):
                    #logger.info("Attribute Field: {}".format(registration[key_N]))
                    attribute=fieldmap[key].split(':')[1] #use key name (after 'attributes:')
                    if(not 'attributes' in temp_dict):
                        temp_dict.update({'attributes':{attribute:registration[key_N].strip()}})
                    else:
                        temp_dict['attributes'].update({attribute:registration[key_N].strip()})
                else:
                    temp_dict.update({fieldmap[key]:registration[key_N].strip()})
                #print(workdict)
            else:
                found_all=False
                #print(registration['teamname'],key_N,"Value Empty")
                errors.append(str(key_N)+ ' is empty')
                if(allFieldsMandatory): 
                    break
        else:
            found_all=False
            #print(registration['teamname'],key_N,"Key Missing")
            errors.append(str(key_N)+ ' not found')
            if(allFieldsMandatory): 
                break

    #print(errors)

    if(allFieldsMandatory and found_all==True) or (not allFieldsMandatory):
        #data_valid=True # Manipulation not necessary as we just don't check the return value anymore where we have set allFieldsMandatory to False
        workdict.update(temp_dict)

    if len(errors) > 0 : errorlist.extend(errors)

    return found_all