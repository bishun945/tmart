

# T-MART: Topography-adjusted Monte-Carlo Adjacency-effect Radiative Transfer code  



from .tmart_class import Tmart_Class

import numpy as np
import pandas as pd
from copy import deepcopy
import random
import math, sys
from scipy.interpolate import interp1d

from .tm_sampling import sample_distance2scatter, sample_Lambertian, sample_scattering
from .tm_geometry import dirP_to_coord, linear_distance, dirC_to_dirP, rotation_matrix, angle_3d, dirC_to_coord
from .tm_intersect import find_atm, intersect_line_DEMtri, find_atm2, intersect_line_DEMtri2
from .tm_intersect import intersect_line_boundary, reflectance_intersect, reflectance_background, intersect_background
from .tm_water import fresnel, sample_cox_munk, find_R_cm

from .tm_move import pt_move
from .tm_OT import find_OT


# inherit and overwrite _run_single_photon
class Tmart(Tmart_Class): 
    
    def _run_single_photon_test(self,pt_id): # test if it's my code that causes multiprocessing not to finish
        return [1,1]
    
    
    # A single photon run 
    def _run_single_photon(self,pt_id):

        if self.print_on: print("\n------- Movement 1 -------")
        
        # numpy atmospheric profile, to runs faster 
        atm_profile = self.atm_profile_wl.sort_values('Alt_bottom').to_numpy()
        

        # Initial position of the photon 
        if self.pixel == None:
            q0 = self.sensor_coords
        else:
            pixel_x = self.Surface.cell_size * (self.pixel[1] + random.random()) # X
            pixel_y = self.Surface.cell_size * (self.pixel[0] + random.random()) # Y

            q0 = self.sensor_coords + [pixel_x,pixel_y,self.pixel_elevation]
            
        
        # Initial moving direction of the photon, 改成 function！！！！！！
        pt_direction = self.target_pt_direction
        
        pt_weight = 1_000_000
        
        # When true, exit atm 
        out = False
        
        # Optimization: when true, skip all scenarios 1 and 2
        black_surface = ((not self.Surface.reflectance.any()) and (not self.Surface.isWater.any()) and 
                         self.Surface.bg_ref[0]==0 and self.Surface.bg_ref[1]==0 and 
                         self.Surface.bg_isWater[0]==0 and self.Surface.bg_isWater[1]==0)
        
        # A numpy array to collect information 
        pt_stat = np.empty((0,12))     
        
        
        ### For loop: photon movements 
        for movement in range(0, 500): 
            
            # sample an optical thickness 
            sampled_tao = -math.log(random.random())
            
            # after moving the sampled_tao, the properties of the photon and the atmosphere layer 
            q1, tao_abs, ot_rayleigh_NA, ot_mie_NA, out = pt_move(atm_profile,q0,pt_direction,sampled_tao)
            # note: ot_rayleigh and ot_mie are replaced later, the accumulated ot should not be used, thus add _NA to mask them
    
    
            if self.print_on:
                print ('\nq0: ' +str(q0))
                print ('q1: ' +str(q1))
                print ('tao_abs: ' +str(tao_abs))
                print('sampled_tao: ' + str(sampled_tao))
                print ('pt_direction: ' +str(pt_direction))
                print('out: ' + str(out)) 
            
            
            
            ### Test atm intrinsic reflectance 
            # if q0[2] <0 or q1[2] < 0:
            #     break
            
            
            ### Test triangle collision             

            # If the two ends of the movement are both above the max elevation of the DEM, skip the test
            if self.Surface.DEM.max() < q0[2] and self.Surface.DEM.max() < q1[2]:
                intersect_tri = pd.DataFrame()  
                
            else:
                # intersect_tri = intersect_line_DEMtri(q0, q1, self.Surface.DEM_triangulated, self.print_on)      
                intersect_tri = intersect_line_DEMtri2(q0, q1, self.Surface.DEM_triangulated, self.print_on)      
            
            
            
            ###### Three scenarios 
            
            # 1 Triangle collision 
            # 2 Background collision 
            # 3 Photon movement and scattering 
            
            # If there is triangle intersection 
            if intersect_tri.shape[0] > 0:
                if self.print_on: print ("\nScenario 1: Triangle collision")
                scenario = 1
            
            # If no triangle intersection 
            else:      
                
                intersect_bg = intersect_background(q0, q1, self.Surface.bg_elevation) 
                intersect_bg_x = intersect_bg[0] < self.Surface.x_min or intersect_bg[0] > self.Surface.x_max
                intersect_bg_y = intersect_bg[1] < self.Surface.y_min or intersect_bg[1] > self.Surface.y_max
                
                # if xy of intersecting background is outside the triangles on X or Y axies 
                if q1[2]<self.Surface.bg_elevation and (intersect_bg_x or intersect_bg_y):     
                    if self.print_on: print ("\nScenario 2: Background collision")
                    scenario = 2 
                else: 
                    if self.print_on: print ("\nScenario 3: Photon movement and scattering ")
                    scenario = 3 
            
            
            ### Black surface acceleration
            
            if (scenario == 1 or scenario == 2) and black_surface: 
                if self.print_on: print ("\n=== Black surface acceleration, exit ===")
                break

            
            ### Triangle Collision 
            
            if scenario == 1:
                
                rotated_cm = None
                
                intersect_tri_chosen = intersect_tri.iloc[intersect_tri.linear_distance.idxmin()] 
                
                q_collision = intersect_tri_chosen.tolist()[0:3]  
                
                if self.print_on: print('q_collision: ' + str(q_collision))    
                
                # re-calculate absorption 
                tao_abs = find_OT(q0,q_collision,atm_profile)
                tao_abs = tao_abs / abs(math.cos(pt_direction[0]/180*math.pi))  
                
                q_collision[2] = q_collision[2] + 0.01 #avoid intersecting again
                q_collision_N = intersect_tri_chosen.tolist()[3:6] #direction of normal 
                q_collision_N_polar = dirC_to_dirP(q_collision_N)
                
                if self.print_on:
                    print("\nNormal to collision: " + str(q_collision_N))
                    print("Normal to collision polar: " + str(q_collision_N_polar))                
                
                q_collision_ref = reflectance_intersect(q_collision, self.Surface.reflectance, 
                                                        self.Surface.cell_size, self.Surface.bg_ref, 
                                                        self.Surface.bg_coords)
                if self.print_on: print("q_collision_ref: " + str(q_collision_ref))    
                
                
                
            
                ### If water --> there is a chance of specular reflectance             
                # Chance determined by Fresnel, pt_weight stays as 1
                # use pt_direction, q_collision_N and Cox-Munk to calculate the new pt_direction 
                
                q_collision_isWater = reflectance_intersect(q_collision, self.Surface.isWater, 
                                                            self.Surface.cell_size, self.Surface.bg_isWater, 
                                                            self.Surface.bg_coords)    
                
                if self.print_on: print('\nq_collision_isWater: '+str(q_collision_isWater))
                
    
                
                # if chance, switch on 
                specular_on = False
                
                # if water, calculate Fresnel reflectance and if specular reflection   
                # q_collision_ref is now R0+
                if q_collision_isWater == 1:
                    
                    in_angle = 100 # just an impossible incident angle 
                    pt_direction_op_C = np.negative(dirP_to_coord(1, pt_direction)) # opposite to pt_direction Coordinates, only for isWater scenarios 
                    

                    
                    while in_angle>90: # if an impossible angle (CM does it sometimes), re-randomize
                    
                        # Use Cox-munk to draw a normal
                        random_cox_munk = sample_cox_munk(self.wind_speed, self.wind_dir)
                        axis = [math.cos((q_collision_N_polar[1]+90)*math.pi/180),
                                math.cos(q_collision_N_polar[1]*math.pi/180),
                                0] 
                        theta = q_collision_N_polar[0]*math.pi/180
                        
                        # tilt cox_munk to the existing polar_N as a new normal 
                        rotated_cm = np.dot(rotation_matrix(axis, theta), random_cox_munk)                    
    
                        # incident angle to calculate Fresnel reflectance 
                        in_angle = angle_3d(rotated_cm, [0,0,0], pt_direction_op_C)
                        

                    
                    R_specular = fresnel(self.water_refraIdx_wl, in_angle)
                    # R_specular = fresnel_test(in_angle, rotated_cm, pt_direction) # testing version, for in_angles > 90
                    
                    R_surf = self.R_wc_wl + (1-self.F_wc_wl) * R_specular # total surface reflectance
                    
                    # modify reflectance, use the original one as R0+ in the absence of white caps 
                    # '(1-self.F_wc_wl) * q_collision_ref' is R0+ in the presence of white caps 
                    q_collision_ref = R_surf + (1-self.F_wc_wl) * q_collision_ref
                    
                    
                    # if chance (R_specular) out of q_collision_ref, siwtch on specular_on
                    specular_on = random.uniform(0,q_collision_ref) < R_specular
                    # specular_on = True # 强制specular, just testing!!!
                    
                    if self.print_on: 
                        print('random_cox_munk: ' + str(random_cox_munk))
                        print("Rotated_cox_munk: " + str(rotated_cm)) 
                        print('Incident angle: ' + str(in_angle))
                        print('F_whitecap: ' + str(self.F_wc_wl))
                        print('R_whitecap: ' + str(self.R_wc_wl))
                        print('R_fresnel: ' + str(R_specular))
                        print('R_surf: ' + str(R_surf))
                        print('specular_on: ' + str(specular_on))
                        print("Modified q_collision_ref: " + str(q_collision_ref))  
                        
                        
                pt_weight = pt_weight * q_collision_ref
                 
                # if water and specular 
                if q_collision_isWater == 1 and specular_on:
                    if self.print_on: print('\n==Specular reflection==')  
                    
                    # Rotate pt_direction_op_C  around rotated_cm by 180 degrees       
                    rotated = np.dot(rotation_matrix(rotated_cm, math.pi), pt_direction_op_C)
       
                    # pt_direction is the specular reflection of the original direction at the new normal 
                    pt_direction = dirC_to_dirP(rotated)[0:2]
                    tpye_collision = 'Ws' # water specular
                    
                # else lambertian 
                else: 
    
                    random_lambertian = sample_Lambertian()
    
                    # axis is azimuthal, clockwise 90 degrees
                    axis = [math.cos((q_collision_N_polar[1]+90)*math.pi/180),
                            math.cos(q_collision_N_polar[1]*math.pi/180),
                            0] 
                    theta = q_collision_N_polar[0]*math.pi/180 #math.pi  # zenith
                    
                    # 000 at the bottom, axis on top, clockwise move
                    rotated = np.dot(rotation_matrix(axis, theta), random_lambertian[0])
                    
                    
                    pt_direction = dirC_to_dirP(rotated)[0:2]
                    tpye_collision = 'W'  # water lambertian 
                    
                    if self.print_on:
                        print("\nRandom_lambertian: " + str(random_lambertian))
                        print("Rotated_lambertian: " + str(rotated)) 
                        print("q_collision_ref: " + str(q_collision_ref))
                        
                if self.print_on: print("pt_weight before absorption: " + str(pt_weight))      
                
                
                
            ### Background collision     
             
            elif scenario == 2:
                
                
                rotated, rotated_cm, intersect_tri_chosen, q_collision_N = None, None, None, None # for plotting, not used 
            
                q_collision_N_polar = [0,0] 
                
                
                q_collision = intersect_bg + [self.Surface.bg_elevation]    
                if self.print_on: print('q_collision: ' + str(q_collision))  
                
                # re-calculate absorption 
                tao_abs = find_OT(q0,q_collision,atm_profile)
                tao_abs = tao_abs / abs(math.cos(pt_direction[0]/180*math.pi))                
                  
                
                q_collision[2] = q_collision[2] + 0.01 #avoid intersecting again
    
                # reflectance of the background at the collision point 
                q_collision_ref = reflectance_background(q_collision,self.Surface.bg_ref, self.Surface.bg_coords)
                if self.print_on:
                    print ('\nOut of the padded DEM')
                    print("q_collision_ref: " + str(q_collision_ref))
                
                # if water 
                q_collision_isWater = reflectance_intersect(q_collision, self.Surface.isWater, 
                                                            self.Surface.cell_size, self.Surface.bg_isWater, 
                                                            self.Surface.bg_coords)    
                if self.print_on: print('\nq_collision_isWater: '+str(q_collision_isWater))                    
                specular_on = False
                
                # if water, calculate Fresnel reflectance and if specular reflection   
                # q_collision_ref is now R0-
                if q_collision_isWater == 1:
                    
                    in_angle = 100 # just an impossible incident angle 
                    pt_direction_op_C = np.negative(dirP_to_coord(1, pt_direction)) # opposite to pt_direction Coordinates, only for isWater scenarios 
                    
                    

                    
                    while in_angle>90: 
                        # Use Cox-munk to draw a normal, no need for rotation
                        random_cox_munk = sample_cox_munk(self.wind_speed, self.wind_dir)
                                       
                        # incident angle to calculate Fresnel reflectance 
                        in_angle = angle_3d(random_cox_munk, [0,0,0], pt_direction_op_C)
                        

                        
                    
                    
                    R_specular = fresnel(self.water_refraIdx_wl, in_angle)
                    R_surf = self.R_wc_wl + (1-self.F_wc_wl) * R_specular # total surface reflectance
                    
                    # modify reflectance, use the original q_collision_ref as R0+
                    q_collision_ref = R_surf + (1-self.F_wc_wl) * q_collision_ref
                    
                    # if chance (R_specular) out of q_collision_ref, siwtch on specular_on
                    specular_on = random.uniform(0,q_collision_ref) < R_specular
      
                    
                    if self.print_on: 
                        print('random_cox_munk: ' + str(random_cox_munk))
                        print('Incident angle: ' + str(in_angle))
                        print('F_whitecap: ' + str(self.F_wc_wl))
                        print('R_whitecap: ' + str(self.R_wc_wl))
                        print('R_fresnel: ' + str(R_specular))
                        print('R_surf: ' + str(R_surf))
                        print('specular_on: ' + str(specular_on))   
                        print("Modified q_collision_ref: " + str(q_collision_ref))  
                
                
                pt_weight = pt_weight * q_collision_ref   
                
                # if water and specular 
                if q_collision_isWater == 1 and specular_on:
                    if self.print_on: print('\n==Specular reflection==')  
                        
                    rotated = np.dot(rotation_matrix(random_cox_munk, math.pi), pt_direction_op_C)
       
                    pt_direction = dirC_to_dirP(rotated)[0:2]
                    tpye_collision = 'Ws'
                    
                # else lambertian 
                else: 
                    pt_direction = dirC_to_dirP(sample_Lambertian()[0])[0:2]
                    tpye_collision = 'W'
                        
                if self.print_on: print("pt_weight before absorption: " + str(pt_weight))               
            
            
            ### Photon movement and scattering 
            
            elif scenario == 3:
                
                q_collision = q1
                
                ### Find ot_mie and ot_rayleigh
                
                ot_rayleigh, ot_mie = find_atm2(atm_profile,q1)
               
                
                pt_direction_op_C = np.negative(dirP_to_coord(1, pt_direction))
                pt_direction, scatt_intensity, type_scat = sample_scattering(ot_mie, ot_rayleigh, pt_direction, self.Atmosphere.aerosol_SPF, self.print_on)
    


    
            
            ###### Calculate absorption 
          
            T_abs = math.exp(-tao_abs) # tao_abs is unchanged if scenario 3 because the whole segment was used
            pt_weight = pt_weight * T_abs
            
            if self.print_on:
                print('\n= Absorption =')
                print("tao_abs: " + str(tao_abs))
                print("T_abs: " + str(T_abs))
                print("pt_weight: " + str(pt_weight))
                print('\n= Local estimate =')
            
            
            ''' to be deleted
            
            # 1000 -> self.pixel_elevation 
            # 30 -> self.sun_dir[0]
            
            sun_dir = [30,0]
            q_collision = np.array([0,0,1000])
            
            dist_120000 = (120_000 - 1000) / np.cos(30/180*np.pi) 
            
            q_sun = dirP_to_coord(dist_120000, sun_dir) + q_collision
            
            '''
            
            
            
             
            
            ###### Local estimates 
            
            # Every movement has a row of local_est
            # Columes: pt_id, movement, type of collision, L_cox-munk, L_whitecap, L_water, L_land, L_rayleigh, L_mie, surface xyz 
            
            
            if_shadow = False
            
            if scenario == 1 or scenario == 2: 
                
                if self.shadow: if_shadow = self.detect_shadow(q_collision)
                    
                if if_shadow:
                    local_est = [pt_id, movement,'Shadow',0,0,0,0,0,0] + q_collision
                
                # Water
                elif q_collision_isWater==1:
                    
                    le_water = self.local_est_water(pt_weight, pt_direction_op_C, q_collision, 
                                                    q_collision_N_polar, R_specular, q_collision_ref, R_surf)
                    local_est = [pt_id, movement,tpye_collision] + le_water + [0,0,0] + q_collision
                        
                # Land 
                else: 
                    le_land = self.local_est_land(q_collision, pt_weight)
                    local_est = [pt_id, movement,'L',0,0,0] + le_land + [0,0] + q_collision
                
                
                if self.print_on: print("local_est: " + str(local_est))
                pt_stat = np.vstack([pt_stat, local_est])     
                
            # Scattering 
            if scenario == 3 and out == False:
                
                if self.shadow: if_shadow = self.detect_shadow(q_collision)
                    
                if if_shadow:
                    local_est = [pt_id, movement,'Shadow',0,0,0,0,0,0] + q_collision.tolist() 
                    # tolist because q_collision comes from q1, which is a numpy array
                    
                else:
                
                    le_scatt = self.local_est_scat(pt_direction_op_C, q_collision, pt_weight, ot_mie, ot_rayleigh, scatt_intensity)
    
                    local_est = [pt_id, movement,type_scat,0,0,0,0] + le_scatt + [0, 0, 0]
                
                if self.print_on: print("local_est: " + str(local_est))
                pt_stat = np.vstack([pt_stat, local_est])            
            
            
            
            
            ###### Plot and out 
            
        
            # Plotting, only supposed to be run by self.run_plot()
            if self.plot_on:
                
                if scenario==1 or scenario == 2:
                    self._plot(q0, q_collision, scenario, intersect_tri_chosen, rotated, q_collision_N, specular_on, rotated_cm) 
                
                else: 
                    self._plot(q0, q_collision, scenario)
                      
        
            # Exit if out 
            if out:
                    
                # Record information ???
                break
        
            if self.print_on: print("\n------- Movement {} -------".format(movement+2))  
            # the last print won't show because the code breaks above
            # +2 because it starts from the 2nd one 
    
            # starting the next movement at the collision         
            q0 = q_collision
        
        
        # return np.array([surface_irradiance]) # for surface_irradiance 
        return pt_stat




    def local_est_scat(self,pt_direction_op_C,q_collision, pt_weight, ot_mie, ot_rayleigh, scatt_intensity):
        
        
        # calculate remaining Transmittance 
        OT = self._local_est_OT(q_collision)
        OT = OT / math.cos(self.sun_dir[0]/180*math.pi)
        T = math.exp(-OT)
        if self.print_on: print ('\nT_total for local_est: ' +str(T))
        
        # total scattering in that layer 
        ot_scattering = ot_mie + ot_rayleigh
        
        
        # angle between pt_direction and the sun 
        angle_pt_sun = angle_3d(dirP_to_coord(1,self.sun_dir), [0,0,0], pt_direction_op_C)
        
        # the angle needed to scatter the photon into the sun's direction 
        angle_scattering = 180 - angle_pt_sun
        
        # rayleigh 
        rayleigh = (3/4)*(1+(math.cos(angle_scattering/180*math.pi))**2)
        # print('rayleigh: ' + str(rayleigh))
        
        # c: contribution? 
        
        rayleigh_c = rayleigh / math.cos(self.sun_dir[0]/180*math.pi)  / 4 # 4 should be the right normalization 
        # print('rayleigh_c: ' + str(rayleigh_c))
        rayleigh_c = rayleigh_c * (ot_rayleigh/ot_scattering)
        # print('rayleigh_c2: ' + str(rayleigh_c))
        
        
        # This function should be built-in in the object to run faster !!!
    
        # mie
        df_angle = self.aerosol_SPF_wl.Angle.to_numpy()
        df_value = self.aerosol_SPF_wl.Value.to_numpy()
        f2 = interp1d(df_angle, df_value, kind='cubic')
        mie = f2(angle_scattering).item()
        
        
        
        mie_c = mie / math.cos(self.sun_dir[0]/180*math.pi) / 4 # / math.pi   
        mie_c = mie_c * (ot_mie/ot_scattering)
        
        
        local_est = np.array([rayleigh_c, mie_c]) * T * pt_weight / 1_000_000   
        
        # print('local_est: ' + str(local_est))
        
        return local_est.tolist()



    def local_est_land(self, q_collision, pt_weight): 
    
        OT = self._local_est_OT(q_collision)
        OT = OT / math.cos(self.sun_dir[0]/180*math.pi)
        T = math.exp(-OT)
        if self.print_on: print ('\nT_total for local_est: ' +str(T))
        
        local_est = pt_weight * T / 1_000_000
        return [local_est]
   
    
      
    def local_est_water(self, pt_weight, pt_direction_op_C, q_collision, q_collision_N_polar, R_specular, q_collision_ref, R_surf):   
        
        # q_collision_ref is modified here
        
        
        R_wc = self.R_wc_wl
        
        
        # Cox-Munk and Fresnel, this one tells us nothing about the actual flux reflectance!!!  
        R_cm = find_R_cm(pt_direction_op_C, self.sun_dir, q_collision_N_polar, 
                         self.wind_dir, self.wind_speed, self.water_refraIdx_wl, self.print_on)
        
        R_cm = (1-self.F_wc_wl) * R_cm # remove whitecaps from cox-munk reflection 
        
        
        OT = self._local_est_OT(q_collision)
        OT = OT / math.cos(self.sun_dir[0]/180*math.pi)
        T = math.exp(-OT)
        
        if self.print_on: print ('\nT_total for local_est: ' +str(T))
            
        # cox-munk
        pt_weight_cm = pt_weight * (R_cm / q_collision_ref) 
        
        # whitecap
        pt_weight_wc = pt_weight * (R_wc / q_collision_ref)
        
        # water-leaving, '(1-self.F_wc_wl) * q_collision_ref' AKA R0+ in the presence of white caps 
        pt_weight_lw = pt_weight * (   (q_collision_ref - R_surf) /  q_collision_ref)
            
        local_est = np.array([pt_weight_cm, pt_weight_wc, pt_weight_lw]) / 1_000_000 
            
        # Absorption 
        local_est = local_est * T 
        return local_est.tolist()
           
    
    def detect_shadow(self, q_collision):
        

        
        dist_120000 = (120_000 - q_collision[2]) / np.cos(self.sun_dir[0]/180*np.pi) 
        q_sun = dirP_to_coord(dist_120000, self.sun_dir) + q_collision
        
        intersect_tri = intersect_line_DEMtri2(q_collision, q_sun, self.Surface.DEM_triangulated, self.print_on)  
        
        if_shadow = intersect_tri.shape[0] > 0
        
        if self.print_on: print ('\nif_shadow: ' +str(if_shadow))
        
        
        return if_shadow
        
        

















